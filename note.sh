#!/bin/bash

GITHUB_TOKEN="$(cat ~/dials/release/.token)" HACKMD_TOKEN="$(cat _HACKMD_TOKEN)" ./note.py "$@"

