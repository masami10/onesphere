# -*- coding: utf-8 -*-

import os
from odoo import api, exceptions, fields, models, _
from odoo.tools import ustr
import logging
import functools
import urllib3
from minio import Minio
from odoo.addons.oneshare_utils.constants import ENV_OSS_BUCKET, ENV_OSS_ENDPOINT, ENV_OSS_ACCESS_KEY, \
    ENV_OSS_SECRET_KEY

_logger = logging.getLogger(__name__)

_http_client = False

def oss_wrapper(raw_resp=True):
    """

    :param raw_resp: boolean, 是否返回urllib3.Response对象
    :return:
    """
    def decorator(f):
        @functools.wraps(f)
        def _oss_wrap(*args, **kw):
            data = None
            resp = None
            try:
                resp = f(*args, **kw)
                data = resp.data
            except Exception as e:
                _logger.error(f"{f.__name__}: {ustr(e)}")
            finally:
                if resp:
                    resp.close()
                    resp.release_conn()
                if raw_resp:
                    return resp
                return data

        return _oss_wrap

    return decorator


class OSSInterface(models.AbstractModel):
    _name = 'onesphere.oss.interface'
    _description = '对象存储接口抽象类'

    # _http_client = None

    def ensure_oss_client(self):
        global _http_client
        if _http_client:
            return _http_client
        ICP = self.env['ir.config_parameter']
        endpoint = ICP.get_param('oss.endpoint', ENV_OSS_ENDPOINT)
        access_key = ICP.get_param('oss.access_key', ENV_OSS_ACCESS_KEY)
        secret_key = ICP.get_param('oss.secret_key', ENV_OSS_SECRET_KEY)
        c = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False,
                  http_client=urllib3.PoolManager(timeout=float(os.environ.get("ODOO_HTTP_SOCKET_TIMEOUT", '20')),
                                                  retries=urllib3.Retry(
                                                      total=5,
                                                      backoff_factor=0.2,
                                                      status_forcelist=[500, 502, 503, 504],
                                                  ),
                                                  ), )
        _http_client = c
        return _http_client

    @oss_wrapper(raw_resp=False)
    def get_oss_object(self, bucket_name: str, object_name: str):
        # 获取minio数据
        c = self.ensure_oss_client()
        return c.get_object(bucket_name, object_name)


    def put_oss_object(self, bucket_name: str, object_name: str, data: bytes, length: int):
        # 上传minio数据
        c = self.ensure_oss_client()
        return c.put_object(bucket_name, object_name, data, length)

