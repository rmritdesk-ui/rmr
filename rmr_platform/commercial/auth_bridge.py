
from fastapi import HTTPException, Request
async def get_current_user(request: Request):
    user=getattr(request.state,'user',None)
    if user is None: raise HTTPException(status_code=401,detail='Authentication required')
    return user
