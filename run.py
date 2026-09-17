import argparse
import os
import uvicorn

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='LastPlate MVP server')
    parser.add_argument('--host',default='0.0.0.0' if 'PORT' in os.environ else '127.0.0.1')
    parser.add_argument('--port',type=int,default=os.environ.get('PORT','8000'))
    args=parser.parse_args()
    uvicorn.run('backend.main:app',host=args.host,port=args.port,workers=1)
