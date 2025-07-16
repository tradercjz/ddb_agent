from typing import Any, Tuple
import dolphindb as ddb
class DatabaseSession:
    """数据库会话管理器"""
    def __init__(self, host: str, port: int, user: str, passwd: str, 
                 keep_alive_time: int = 3600, reconnect: bool = True, logger=None):
        self.host = host 
        self.port = port
        self.user = user 
        self.passwd = passwd
        self.keep_alive_time = keep_alive_time
        self.reconnect = reconnect
        self.session = ddb.session()
        self.logger = logger
        self.isConnected = False

    def __enter__(self):
        self.session.connect(
            self.host, 
            int(self.port), 
            self.user, 
            self.passwd,
            keepAliveTime=self.keep_alive_time, 
            reconnect=self.reconnect
        )
        self.isConnected = True
        return self 

    def __exit__(self, exc_type, exc_value, traceback):
        self.session.close()
        self.isConnected = False

    
    def execute(self, script: str) -> Tuple[bool, Any]:
        """执行DolphinDB脚本并返回结果或错误"""
        try:
            result = self.session.run(script)
            return True, result
        except Exception as e:
            return False, str(e) 

    def connect(self):
        """显式建立连接（可多次调用，已连则跳过）"""
        if not self.isConnected:
            self.session.connect(
                self.host, 
                int(self.port), 
                self.user, 
                self.passwd,
                keepAliveTime=self.keep_alive_time, 
                reconnect=self.reconnect
            )

    def close(self):
        """显式关闭连接"""
        if self.isConnected:
            self.session.close()
            self.isConnected = False
