#!/bin/bash

GITHUB_TOKEN="$(cat DIALS_TOKEN)" HACKMD_TOKEN="$(cat _HACKMD_TOKEN)" poetry run python3 note.py "$@"

