import sys
import time
import pytracy

print("Python:", sys.version)
print("PyTracy:", pytracy.__file__)

pytracy.enable_tracing(True)

print("Profile:", sys.getprofile())
print("Trace:", sys.gettrace())

def inner():
    return sum(i * i for i in range(100_000))

def outer():
    for _ in range(10):
        inner()

print("Connect Tracy now")

for _ in range(60):
    outer()
    time.sleep(0.5)