import random
import string
import re

from typing import *

def make_unique_id(length:int=8)->str:
    # Generate a random string of the specified length from ASCII letters and digits
    characters = string.ascii_uppercase
    unique_id = "".join(random.choices(characters, k=length))
    return unique_id


def make_unique_name(name:str, names:Iterable[str])->str:
    # Regex to extract the name part (without trailing digits)
    names = set(_ for _ in names)
    match = re.search(r"(.*?)(\d*)$", name)
    if match:
        # Name part without digits
        name_part = match.group(1)

        # Loop to find a unique name
        digit = 1
        while name in names:
            # Append the current digit to the name part
            name = f"{name_part}{digit}"
            digit += 1

    return name