#!/usr/bin/python3
from podcomm.pr_rileylink import RileyLink
from podcomm.definitions import *


logger = getLogger()

print("connecting to RL..")
r = RileyLink()
r.connect()
print("Connected. Verifying radio settings..")
r.init_radio(force_init=True)
info = r.get_info()
print(info)
print("All looks good.")