class StageError(Exception):
    def __init__(self, stage, code, message, http_status=500):
        super().__init__(message)
        self.stage,self.code,self.message=stage,code,message
        self.http_status=http_status
    def as_dict(self):
        return dict(stage=self.stage,code=self.code,message=self.message,http_status=self.http_status,
                    kind='conflict' if self.http_status==409 else 'input' if self.http_status==422 else 'server')
