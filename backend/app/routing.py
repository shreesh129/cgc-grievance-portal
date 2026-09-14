CHAIN=["mentor","administration","hod","dean","managing_director","vice_chancellor"]
def initial_handler(role,sub_category,target_authority):
    s=sub_category.lower().replace(" ","_")
    if role=="student" and "mentor" in s: return "administration",1
    if role=="teacher" and target_authority in {"administration","hod"}: 
        return target_authority,CHAIN.index(target_authority)
    return "mentor",0
def next_handler(current):
    if current not in CHAIN:return None
    i=CHAIN.index(current)
    return CHAIN[i+1] if i+1<len(CHAIN) else None
