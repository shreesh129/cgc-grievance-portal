from pydantic import BaseModel,Field,ConfigDict
from typing import Literal

class LoginRequest(BaseModel):
    login_id:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=1,max_length=128)
    portal:str|None=None

class ComplaintText(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    role:Literal["student","teacher"]
    user_id:str=Field(min_length=1,max_length=80)
    user_name:str=Field(default="",max_length=160)
    anonymous:bool=False
    portal:Literal["college","hostel","common","mess","hr","staffroom"]
    category:str=Field(min_length=1,max_length=100)
    sub_category:str=Field(min_length=1,max_length=160)
    description:str=Field(min_length=3,max_length=10000)
    gender:str|None=Field(default=None,max_length=20)
    hostel:str|None=Field(default=None,max_length=80)
    block_no:str|None=Field(default=None,max_length=50)
    class_no:str|None=Field(default=None,max_length=80)
    lab_no:str|None=Field(default=None,max_length=80)
    staffroom:str|None=Field(default=None,max_length=100)
    target_authority:Literal["administration","hod"]|None=None

class StatusUpdate(BaseModel):
    status:Literal["under_review","resolved","closed"]
    note:str=Field(default="",max_length=3000)

class Readdressal(BaseModel):
    reason:str=Field(min_length=3,max_length=3000)

class FeedbackIn(BaseModel):
    rating:int=Field(ge=1,le=5)
    comment:str|None=Field(default=None,max_length=2000)

class IntegratedUser(BaseModel):
    login_id:str=Field(min_length=1,max_length=80)
    name:str=Field(min_length=1,max_length=160)
    role:Literal["student","teacher","mentor","administration","hod","dean","managing_director","vice_chancellor"]
    password:str|None=Field(default=None,max_length=128)
    department:str|None=None; designation:str|None=None; email:str|None=None; phone:str|None=None
    mentor_login_id:str|None=None; source_system:str="college_erp"; external_id:str|None=None; active:bool=True

class DeveloperConfig(BaseModel):
    escalation_days:int|None=Field(default=None,ge=1,le=365)
    max_audio_mb:int|None=Field(default=None,ge=1,le=100)
