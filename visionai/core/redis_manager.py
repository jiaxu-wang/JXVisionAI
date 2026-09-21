"""
Redis 访问层：流配置、检测记录、人脸库元数据。

键前缀由 ``REDIS_KEY_PREFIX``（默认 ``visionai/``）决定，与 Python 包名无关。
本类为进程内单例；连接失败时相关读写降级为空/跳过，避免拖垮检测线程。
"""

import os
import redis
import json
import logging
from datetime import date, datetime, timedelta
from visionai.config.settings import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB,
    REDIS_KEY_PREFIX, DETECTION_RETENTION_DAYS
)

logger = logging.getLogger(__name__)

class RedisManager:
    """封装流配置与检测记录的 Redis 读写。"""
    
    _instance = None
    _redis_client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisManager, cls).__new__(cls)
            cls._instance._init_redis()
        return cls._instance
    
    def _init_redis(self):
        """建立连接并 ping；失败则 ``_redis_client`` 置空。"""
        try:
            # lib_name/lib_version=None：避免 redis-py 发送 CLIENT SETINFO（在 MISCONF 只读时会导致 ping 失败）
            self._redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=3,
                lib_name=None,
                lib_version=None,
            )
            try:
                self._redis_client.ping()
            except redis.exceptions.ResponseError as e:
                # RDB 落盘失败时 Redis 可能拒绝写命令；先放开再探测
                if "MISCONF" in str(e):
                    try:
                        self._redis_client.execute_command(
                            "CONFIG", "SET", "stop-writes-on-bgsave-error", "no"
                        )
                    except Exception:
                        pass
                    self._redis_client.ping()
                else:
                    raise
            logger.info("Redis连接成功")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            self._redis_client = None
    
    def is_connected(self):
        """检查是否连接到Redis"""
        if self._redis_client is None:
            return False
        try:
            self._redis_client.ping()
            return True
        except Exception:
            return False
    
    def _get_stream_hash_key(self, stream_id):
        """获取视频流检测记录的Redis Hash键"""
        return f"{REDIS_KEY_PREFIX}{stream_id}"
    
    def get_stream_id_by_name(self, stream_name):
        """根据流名称获取流 ID（如 stream_938a7923）。"""
        streams = self.get_streams()
        for stream in streams:
            if stream.get("name") == stream_name:
                return stream.get("id")
        return None
    
    def save_detection(
        self,
        stream_name,
        detection_types,
        image_path,
        timestamp=None,
        object_key=None,
        storage_kind=None,
        extra=None,
        record_id=None,
    ):
        """
        保存检测结果到Redis（使用Hash结构）
        
        Args:
            stream_name: 摄像头名称
            detection_types: 检测类型列表，如 ["人物", "手机"]
            image_path: 本地截图路径（可空，若仅对象存储）
            object_key: 对象存储中的键（S3 等）
            storage_kind: 如 s3
            timestamp: 时间戳（可选，默认当前时间）
        
        Returns:
            检测记录时间戳，失败返回None
        """
        if not self.is_connected():
            logger.warning("Redis未连接，无法保存检测结果")
            return None
        
        try:
            if timestamp is None:
                from visionai.utils.timeutil import app_now

                timestamp = app_now()
            
            # 获取流ID
            stream_id = self.get_stream_id_by_name(stream_name)
            if not stream_id:
                logger.warning(f"未找到流 {stream_name} 对应的ID，使用默认ID")
                stream_id = f"unknown_{stream_name}"
            
            # Hash field：显式 record_id（同秒多类型）或 unix 秒；已存在则加后缀避免覆盖
            hash_key = self._get_stream_hash_key(stream_id)
            timestamp_str = str(record_id).strip() if record_id else str(int(timestamp.timestamp()))
            if not timestamp_str:
                timestamp_str = str(int(timestamp.timestamp()))
            base_id = timestamp_str
            n = 0
            while self._redis_client.hexists(hash_key, timestamp_str):
                n += 1
                timestamp_str = f"{base_id}_{n}"
            
            # 构建检测数据
            detection_data = {
                "id": timestamp_str,
                "stream_id": stream_id,
                "stream_name": stream_name,
                "detection_types": detection_types,
                "image_path": image_path or "",
                "timestamp": timestamp.isoformat()
            }
            if object_key:
                detection_data["object_key"] = object_key
            if storage_kind:
                detection_data["storage_kind"] = storage_kind
            if extra:
                detection_data["extra"] = extra
            
            # 保存到Hash
            self._redis_client.hset(
                hash_key,
                timestamp_str,
                json.dumps(detection_data, ensure_ascii=False)
            )
            
            # 设置Hash过期时间
            self._redis_client.expire(
                hash_key,
                timedelta(days=DETECTION_RETENTION_DAYS)
            )
            
            logger.info(f"检测结果已保存到Redis Hash: {stream_name}({stream_id}) - {detection_types}")
            return timestamp_str
            
        except Exception as e:
            logger.error(f"保存检测结果到Redis失败: {e}")
            return None
    
    @staticmethod
    def _detection_doc_datetime_naive(doc):
        ts = doc.get("timestamp")
        if not ts:
            return None
        try:
            from visionai.utils.timeutil import app_tz

            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                # 旧数据无时区：按应用时区理解（修复前容器 UTC 写入的仍会偏，无法自动纠正）
                dt = dt.replace(tzinfo=app_tz())
            return dt.astimezone(app_tz()).replace(tzinfo=None)
        except ValueError:
            return None

    def _list_detections_sorted(self, stream_id=None):
        """列出检测记录（单流或全部），按时间降序。"""
        all_detections = []
        if stream_id:
            hash_key = self._get_stream_hash_key(stream_id)
            stream_data = self._redis_client.hgetall(hash_key)
            for ts_str, data_str in stream_data.items():
                try:
                    all_detections.append(json.loads(data_str))
                except Exception:
                    pass
        else:
            streams = self.get_streams()
            for stream in streams:
                sid = stream.get("id")
                if sid:
                    hash_key = self._get_stream_hash_key(sid)
                    stream_data = self._redis_client.hgetall(hash_key)
                    for ts_str, data_str in stream_data.items():
                        try:
                            all_detections.append(json.loads(data_str))
                        except Exception:
                            pass
        all_detections.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return all_detections

    def get_detections(
        self,
        stream_id=None,
        limit=50,
        offset=0,
        time_start=None,
        time_end=None,
        detection_type=None,
    ):
        """
        获取检测记录（支持时间范围、检测类型过滤；stream_id 表示只查该流）。

        Args:
            stream_id: 视频流 ID，None 表示全部流
            limit / offset: 在过滤结果上分页
            time_start / time_end:  naive datetime，含端点；None 表示不限制
            detection_type: 与 detection_types 列表项精确匹配（如「人物」「打电话」）

        Returns:
            (当前页列表, 过滤后总条数)
        """
        if not self.is_connected():
            logger.warning("Redis未连接，无法获取检测结果")
            return [], 0

        try:
            if time_start and time_end and time_start > time_end:
                time_start, time_end = time_end, time_start

            all_detections = self._list_detections_sorted(stream_id=stream_id)
            filtered = []
            for doc in all_detections:
                dt = self._detection_doc_datetime_naive(doc)
                if time_start is not None:
                    if dt is None or dt < time_start:
                        continue
                if time_end is not None:
                    if dt is None or dt > time_end:
                        continue
                if detection_type:
                    types = doc.get("detection_types") or []
                    if detection_type not in types:
                        continue
                filtered.append(doc)

            total = len(filtered)
            page = filtered[offset : offset + limit]
            return page, total

        except Exception as e:
            logger.error(f"获取检测结果失败: {e}")
            return [], 0

    def get_detection_by_id(self, detection_id):
        """
        按记录 ID（时间戳字符串）查找单条检测记录；跨所有已配置流。
        """
        if not self.is_connected():
            return None
        try:
            for stream in self.get_streams():
                sid = stream.get("id")
                if not sid:
                    continue
                hash_key = self._get_stream_hash_key(sid)
                data_str = self._redis_client.hget(hash_key, str(detection_id))
                if data_str:
                    try:
                        return json.loads(data_str)
                    except json.JSONDecodeError:
                        return None
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"查询检测记录失败: {e}")
            return None
    
    def get_detection_count(self, stream_id=None):
        """
        获取检测记录数量
        
        Args:
            stream_id: 视频流ID（可选，None表示获取所有）
        
        Returns:
            检测记录数量
        """
        if not self.is_connected():
            return 0
        
        try:
            count = 0
            
            if stream_id:
                # 获取指定流的检测记录数量
                hash_key = self._get_stream_hash_key(stream_id)
                count = self._redis_client.hlen(hash_key)
            else:
                # 获取所有流的检测记录数量
                streams = self.get_streams()
                for stream in streams:
                    sid = stream.get("id")
                    if sid:
                        hash_key = self._get_stream_hash_key(sid)
                        count += self._redis_client.hlen(hash_key)
            
            return count
        except Exception as e:
            logger.error(f"获取检测记录数量失败: {e}")
            return 0
    
    def count_detections_today(self):
        """
        统计当前服务器本地日期「今天」内的检测记录条数（与历史告警同源，按各流 Hash 内 timestamp 判断）。
        """
        if not self.is_connected():
            return 0
        today = date.today()
        n = 0
        try:
            for stream in self.get_streams():
                sid = stream.get("id")
                if not sid:
                    continue
                hash_key = self._get_stream_hash_key(sid)
                for data_str in self._redis_client.hvals(hash_key):
                    try:
                        doc = json.loads(data_str)
                        ts = doc.get("timestamp")
                        if not ts:
                            continue
                        ts_str = str(ts).replace("Z", "+00:00")
                        dt = datetime.fromisoformat(ts_str)
                        if dt.tzinfo is not None:
                            dt = dt.astimezone().replace(tzinfo=None)
                        if dt.date() == today:
                            n += 1
                    except (ValueError, TypeError, OSError, json.JSONDecodeError):
                        continue
            return n
        except Exception as e:
            logger.error(f"统计今日告警失败: {e}")
            return 0
    
    def delete_detection(self, stream_id, timestamp_str):
        """
        删除指定的检测记录
        
        Args:
            stream_id: 视频流ID
            timestamp_str: 时间戳字符串
        
        Returns:
            是否成功删除
        """
        if not self.is_connected():
            return False

        from visionai.core.object_storage import get_object_storage

        try:
            hash_key = self._get_stream_hash_key(stream_id)
            data_str = self._redis_client.hget(
                hash_key, str(timestamp_str)
            )
            if data_str:
                try:
                    doc = json.loads(data_str)
                except json.JSONDecodeError:
                    doc = {}
                okey = doc.get("object_key")
                if okey:
                    st = get_object_storage()
                    if st:
                        st.delete_object(okey)
                ip = doc.get("image_path")
                if ip and os.path.isfile(ip):
                    try:
                        os.remove(ip)
                    except OSError:
                        pass
            result = self._redis_client.hdel(
                hash_key, str(timestamp_str)
            )
            if result > 0:
                logger.info(
                    f"检测记录已删除: {stream_id} - {timestamp_str}"
                )
                return True
            return False

        except Exception as e:  # noqa: BLE001
            logger.error(f"删除检测记录失败: {e}")
            return False
    
    def delete_detection_by_id(self, detection_id):
        """
        通过ID删除检测记录（兼容旧接口）
        
        Args:
            detection_id: 检测记录ID（即时间戳）
        
        Returns:
            是否成功删除
        """
        if not self.is_connected():
            return False

        from visionai.core.object_storage import get_object_storage

        try:
            # 遍历所有流查找该记录
            streams = self.get_streams()
            for stream in streams:
                sid = stream.get("id")
                if sid:
                    hash_key = self._get_stream_hash_key(sid)
                    data_str = self._redis_client.hget(
                        hash_key, str(detection_id)
                    )
                    if data_str:
                        try:
                            doc = json.loads(data_str)
                        except json.JSONDecodeError:
                            doc = {}
                        okey = doc.get("object_key")
                        if okey:
                            st = get_object_storage()
                            if st:
                                st.delete_object(okey)
                        ip = doc.get("image_path")
                        if ip and os.path.isfile(ip):
                            try:
                                os.remove(ip)
                            except OSError:
                                pass
                        self._redis_client.hdel(hash_key, str(detection_id))
                        logger.info(
                            f"检测记录已删除: {sid} - {detection_id}"
                        )
                        return True
            return False

        except Exception as e:  # noqa: BLE001
            logger.error(f"删除检测记录失败: {e}")
            return False
    
    def delete_detections(self, detection_ids):
        """
        批量删除检测记录
        
        Args:
            detection_ids: 检测记录ID列表
        
        Returns:
            成功删除的数量
        """
        count = 0
        for detection_id in detection_ids:
            if self.delete_detection_by_id(detection_id):
                count += 1
        return count
    
    def cleanup_expired(self):
        """清理过期的检测记录（Redis的过期机制会自动处理，这里可以手动触发）"""
        # Redis的过期机制会自动处理，这里可以添加额外的清理逻辑
        pass
    
    def _get_stream_list_key(self):
        """获取流配置列表的Redis键"""
        return f"{REDIS_KEY_PREFIX}streamlist"
    
    def get_streams(self):
        """
        获取所有流配置
        
        Returns:
            流配置列表
        """
        if not self.is_connected():
            logger.warning("Redis未连接，无法获取流配置")
            return []
        
        try:
            hash_key = self._get_stream_list_key()
            stream_data = self._redis_client.hgetall(hash_key)
            
            streams = []
            for stream_id, data_str in stream_data.items():
                try:
                    stream = json.loads(data_str)
                    streams.append(stream)
                except:
                    pass
            
            return streams
        except Exception as e:
            logger.error(f"获取流配置失败: {e}")
            return []
    
    def save_stream(self, stream):
        """
        保存单个流配置
        
        Args:
            stream: 流配置字典（必须包含id字段）
        
        Returns:
            是否成功
        """
        if not self.is_connected():
            logger.warning("Redis未连接，无法保存流配置")
            return False
        
        try:
            stream_id = stream.get("id")
            if not stream_id:
                logger.error("流配置缺少id字段")
                return False
            
            hash_key = self._get_stream_list_key()
            self._redis_client.hset(
                hash_key,
                stream_id,
                json.dumps(stream, ensure_ascii=False)
            )
            
            logger.info(f"流配置已保存: {stream_id}")
            return True
        except Exception as e:
            logger.error(f"保存流配置失败: {e}")
            return False
    
    def save_streams(self, streams):
        """
        批量保存流配置（会覆盖原有所有流配置）
        
        Args:
            streams: 流配置列表
        
        Returns:
            是否成功
        """
        if not self.is_connected():
            logger.warning("Redis未连接，无法保存流配置")
            return False
        
        try:
            hash_key = self._get_stream_list_key()
            
            # 删除原有所有流配置
            self._redis_client.delete(hash_key)
            
            # 保存新的流配置
            for stream in streams:
                stream_id = stream.get("id")
                if stream_id:
                    self._redis_client.hset(
                        hash_key,
                        stream_id,
                        json.dumps(stream, ensure_ascii=False)
                    )
            
            logger.info(f"流配置已批量保存，共{len(streams)}个流")
            return True
        except Exception as e:
            logger.error(f"批量保存流配置失败: {e}")
            return False
    
    def delete_stream(self, stream_id):
        """
        删除流配置
        
        Args:
            stream_id: 流ID
        
        Returns:
            是否成功
        """
        if not self.is_connected():
            logger.warning("Redis未连接，无法删除流配置")
            return False
        
        try:
            hash_key = self._get_stream_list_key()
            result = self._redis_client.hdel(hash_key, stream_id)
            
            if result > 0:
                logger.info(f"流配置已删除: {stream_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除流配置失败: {e}")
            return False
    
    def init_streams_from_config(self):
        """
        从settings.py初始化流配置到Redis（仅在Redis中没有流配置时执行）
        """
        if not self.is_connected():
            return
        
        try:
            # 检查Redis中是否已有流配置
            existing_streams = self.get_streams()
            if existing_streams:
                logger.info("Redis中已有流配置，跳过初始化")
                return
            
            # 从settings.py导入配置
            from visionai.config.settings import STREAMS as config_streams
            
            if config_streams:
                self.save_streams(config_streams)
                logger.info("已从配置文件初始化流配置到Redis")
        except Exception as e:
            logger.error(f"初始化流配置失败: {e}")

    def _face_library_hash_key(self) -> str:
        return f"{REDIS_KEY_PREFIX}face_library:persons"

    def get_all_face_persons(self) -> dict[str, dict]:
        """返回 {person_id: meta_dict}。"""
        if not self.is_connected():
            return {}
        try:
            raw = self._redis_client.hgetall(self._face_library_hash_key())
            out: dict[str, dict] = {}
            for pid, data_str in (raw or {}).items():
                try:
                    out[str(pid)] = json.loads(data_str)
                except json.JSONDecodeError:
                    pass
            return out
        except Exception as e:  # noqa: BLE001
            logger.error("读取人脸库 Redis 失败: %s", e)
            return {}

    def get_face_person(self, person_id: str) -> dict | None:
        if not self.is_connected():
            return None
        try:
            data_str = self._redis_client.hget(
                self._face_library_hash_key(), str(person_id)
            )
            if not data_str:
                return None
            return json.loads(data_str)
        except Exception as e:  # noqa: BLE001
            logger.error("读取人员 %s 失败: %s", person_id, e)
            return None

    def save_face_person(self, person_id: str, meta: dict) -> bool:
        if not self.is_connected():
            logger.warning("Redis未连接，无法保存人脸库")
            return False
        try:
            self._redis_client.hset(
                self._face_library_hash_key(),
                str(person_id),
                json.dumps(meta, ensure_ascii=False),
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("保存人员 %s 失败: %s", person_id, e)
            return False

    def delete_face_person(self, person_id: str) -> bool:
        if not self.is_connected():
            return False
        try:
            n = self._redis_client.hdel(
                self._face_library_hash_key(), str(person_id)
            )
            return n > 0
        except Exception as e:  # noqa: BLE001
            logger.error("删除人员 %s 失败: %s", person_id, e)
            return False

    def _plate_library_hash_key(self) -> str:
        return f"{REDIS_KEY_PREFIX}plate_library:plates"

    def get_all_plates(self) -> dict[str, dict]:
        """返回 {plate_no: meta_dict}。"""
        if not self.is_connected():
            return {}
        try:
            raw = self._redis_client.hgetall(self._plate_library_hash_key())
            out: dict[str, dict] = {}
            for plate_no, data_str in (raw or {}).items():
                try:
                    out[str(plate_no)] = json.loads(data_str)
                except json.JSONDecodeError:
                    pass
            return out
        except Exception as e:  # noqa: BLE001
            logger.error("读取车牌库 Redis 失败: %s", e)
            return {}

    def save_plate(self, plate_no: str, meta: dict) -> bool:
        if not self.is_connected():
            logger.warning("Redis未连接，无法保存车牌库")
            return False
        try:
            self._redis_client.hset(
                self._plate_library_hash_key(),
                str(plate_no),
                json.dumps(meta, ensure_ascii=False),
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("保存车牌 %s 失败: %s", plate_no, e)
            return False

    def delete_plate(self, plate_no: str) -> bool:
        if not self.is_connected():
            return False
        try:
            n = self._redis_client.hdel(
                self._plate_library_hash_key(), str(plate_no)
            )
            return n > 0
        except Exception as e:  # noqa: BLE001
            logger.error("删除车牌 %s 失败: %s", plate_no, e)
            return False


# 全局Redis管理器实例
redis_manager = RedisManager()

# 初始化流配置
redis_manager.init_streams_from_config()
