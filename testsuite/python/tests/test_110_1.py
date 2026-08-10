############################################################################
# Copyright (C) SchedMD LLC.
############################################################################
import re

import atf


def test_usage():
    """Verify sgather --usage has the correct format"""

    atf.require_tool("sgather")
    output = atf.run_command_output("sgather --usage", fatal=True)
    assert re.search(r"Usage: sgather \[-[A-Za-z]+\] SOURCE DEST$", output) is not None
