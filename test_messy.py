# SPDX-License-Identifier: AGPL-3.0
# Intentionally messy test file for PyStreamliner

import os, sys, json, typing
from typing import List, Dict, Optional, Union, Any
from collections import defaultdict, Counter

if typing.TYPE_CHECKING:
    from collections import deque
    from pathlib import Path
    from os import path

import re as regex
from datetime import datetime, timedelta

x = 42
temp = "temporary"
foo = [1, 2, 3]
id = "shadowed"
list = [10, 20, 30]

def complex_accumulator(base_value: int) -> int:
    if base_value > 100:
        total = base_value + 10
    else:
        total = base_value + 10

    y = [item * 2 for item in range(10) if item % 2 == 0]
    scrambler = lambda id, len: id + len   # vague + shadowed params
    unused_result = scrambler(5, 3)

    return total

class DataProcessor:
    active_profile: str
    timeout_limit: int = 30

    def __init__(self) -> None:
        self.data = []
        unused_local = "ghost"
        tmp = 99

    def dead_weight_method(self):
        """This method is never called."""
        pass

    def another_unused(self, a, b, c):
        bar = a + b
        return None

def helper_that_is_never_called():
    z = 100
    return z

if __name__ == "__main__":
    print("This should stay")
    processor = DataProcessor()

