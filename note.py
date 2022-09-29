import sys
import requests
from pathlib import Path
from pprint import pprint
import re
import datetime
import json
import dateutil.parser
import textwrap
from pydantic import BaseSettings
import base64
from argparse import ArgumentParser

BOLD = "\033[1m"
BLUE = "\033[34m"
NC = "\033[0m"
GRAY = "\033[37m"


class Settings(BaseSettings):
    HACKMD_TOKEN: str
    GITHUB_TOKEN: str


# HACKMD_TOKEN = Path(".HACKMD_TOKEN").read_text().strip()

settings = Settings()
parser = ArgumentParser(description="Handle updating and creation of new dials-core notes")
parser.parse_args()


def date_suffix(day):
    """
    English ordinal suffix for the day of the month, 2 characters; i.e.
    'st', 'nd', 'rd' or 'th'.

    From Django.
    """
    if day in (11, 12, 13):  # Special case
        return "th"
    last = day % 10
    if last == 1:
        return "st"
    if last == 2:
        return "nd"
    if last == 3:
        return "rd"
    return "th"


def request(method: str, url: str, **kwargs):
    """Run a request with auth, exit on error. Returns the decoded json."""
    args = dict(kwargs)
    headers = {
        "Authorization": f"Bearer {settings.HACKMD_TOKEN}",
        **args.pop("headers", {}),
    }
    r = requests.request(method, url, headers=headers, **kwargs)
    if not r.ok:
        sys.exit(f"Error requesting {method} {url}: {r.status_code} \n{r.text}")
    return r.json()


#if not Path("_cache").is_file():
team_notes = request("GET", "https://api.hackmd.io/v1/teams/dials/notes")
Path("_cache").write_text(json.dumps(team_notes))
#else:
#    print("Loading from _cache")
#    team_notes = json.loads(Path("_cache").read_text())

reMeetingDate = re.compile("DIALS (?:core )?meeting (\d+)-(\d+)-(\d+)", re.I)

meetings = {}
for note in team_notes:
    if not (match := reMeetingDate.match(note["title"])):
        print(f"{GRAY}Ignoring: {note['title']}{NC}")
        continue
    y, m, d = match.groups()
    meeting_date = datetime.date(int(y), int(m), int(d))
    meetings[meeting_date] = note

# Find the last meeting, for establishing cadence
last_meeting = sorted(meetings.keys())[-1]

print(f"The last meeting note is for: {BOLD}{last_meeting}{NC}")
# Is this today, in the future, or past?
if last_meeting == datetime.date.today():
    # _continue = input("Meeting for today exists: Create next meeting [yN]?").lower().startswith("y")
    _continue = True
    if not _continue:
        print("Declined to create new meeting, nothing to do.")
        sys.exit()
elif last_meeting > datetime.date.today():
    print(f"Future meeting {last_meeting} already exists.")
    sys.exit()

# The last meeting is in the past. Work out the next expected meeting date
next_meeting = last_meeting + datetime.timedelta(weeks=2)
print(f"\nNext meeting expected on: {BOLD}{next_meeting}{NC}")
confirmation_date = input(
    "Please confirm, blank for yes, or new date to replace: "
).strip() or str(next_meeting)
next_meeting = dateutil.parser.isoparse(confirmation_date).date()

print(f"Next meeting: {BOLD}{next_meeting}{NC}")

# Get this previous note, to transplant the contents to our new template

_old_note = request(
    "GET", f"https://api.hackmd.io/v1/notes/{meetings[last_meeting]['id']}"
)["content"]
previous_note_contents = _old_note[
    _old_note.index("## Previous Actions") : _old_note.index("### Next meeting")
]


def _generate_next_meeting_text(next_meeting):
    """Generate the suffix saying when the next meeting is (or could be)"""
    # Work out what the meeting _after_ this would be, so we can write the "next meeting"
    next_next_meeting = next_meeting + datetime.timedelta(weeks=2)

    # Work out if datetime is ambiguous for normal meeting times
    tz_uk = dateutil.tz.gettz("Europe/London")
    tz_us = dateutil.tz.gettz("America/Los_Angeles")

    # The standard meeting times, that we expect to stay static
    uk_standard_meeting_time = datetime.time(16, 00)
    us_standard_meeting_time = datetime.time(8, 00)

    uk_expected_meeting = datetime.datetime.combine(
        next_next_meeting, uk_standard_meeting_time, tzinfo=tz_uk
    )
    us_equivalent_meeting = uk_expected_meeting.astimezone(tz_us)

    def _time_and_zone(dt):
        """Generate the 'time (timezone)' string"""
        return f"{dt.strftime('%I%p').lstrip('0').lower()} ({dt.tzinfo.tzname(dt)})"

    uk_time_string = _time_and_zone(uk_expected_meeting)
    us_time_string = _time_and_zone(us_equivalent_meeting)

    next_meeting_date = (
        f"{next_next_meeting:%A, %B} {next_next_meeting.day}{date_suffix(next_next_meeting.day)}"
    )

    # Now, if the US equivalent is not at the expected time, we have a conflict
    if us_equivalent_meeting.time() == us_standard_meeting_time:
        return f"{next_meeting_date}, {uk_time_string}, {us_time_string}"
    else:
        print(
            f"Detected timezone conflict, US {us_equivalent_meeting.time()} != {us_standard_meeting_time}, meeting must move or be cancelled"
        )
        # Work out the inverse, the UK meeting time assuming fixed US
        us_expected = datetime.datetime.combine(
            next_next_meeting, us_standard_meeting_time, tzinfo=tz_us
        )
        uk_equivalent = us_expected.astimezone(tz_uk)
        uk_time_string_alt = _time_and_zone(uk_equivalent)
        us_time_string_alt = _time_and_zone(us_expected)
        return textwrap.dedent(
            f"""
        Due to time zone changes the normal meeting time must change:

        {next_meeting_date}, {uk_time_string}, {us_time_string}

        or

        {next_meeting_date}, {uk_time_string_alt}, {us_time_string_alt}
        """
        )


meeting_title = f"DIALS core meeting {next_meeting}"

next_meeting_text = _generate_next_meeting_text(next_meeting)

# Generate the new meeting
# previous_note_contents
new_agenda = f"""
---
name: {meeting_title}
tags: core meeting
---

# {meeting_title}

{previous_note_contents}

### Next meeting

{next_meeting_text}
""".lstrip()

print(f"New meeting agenda from template:\n{BLUE}{new_agenda}{NC}")

response = input("Create new note? [Yn]")
if response and not response.lower().startswith("y"):
    print("Not creating.")
    sys.exit()

new_note = request(
    "POST",
    "https://api.hackmd.io/v1/teams/dials/notes",
    json={
        "title": meeting_title,
        "content": new_agenda,
        "readPermission": "guest",
        "writePermission": "signed_in",
    },
)

note_id = new_note["id"]


future_meeting_text = f"""
---
name: {meeting_title}
tags: core meeting
---

# {meeting_title}

[![hackmd-github-sync-badge](https://hackmd.io/{note_id}/badge)](https://hackmd.io/{note_id})

This is a future meeting, please see the WIP agenda at [hackmd.io](https://hackmd.io/{note_id})


### Next meeting

{next_meeting_text}
""".lstrip()

repo_user = "dials"
repo_name = "kb"
repo_branch = "master"
file_path = f"collections/_core/{next_meeting}.md"


# Get the current HEAD id on github for the target repository
resp = requests.request(
    "POST",
    "https://api.github.com/graphql",
    headers={"Authorization": f"bearer {settings.GITHUB_TOKEN}"},
    json={"query": f"""query {{ repository(owner: "{repo_user}", name: "{repo_name}") {{
    id
    ref(qualifiedName: "refs/heads/{repo_branch}") {{
      target {{
        oid
        ... on Commit {{
            file(path: "{file_path}") {{
                object {{
                    ... on Blob {{
                        text
                    }}
                }}
            }}
        }}
      }}
    }}
  }} }}"""},
)
resp.raise_for_status()

target = resp.json()["data"]["repository"]["ref"]["target"]
existing_oid = target["oid"]

if "file" in target and target["file"]:
    existing_content = target["file"]["object"]["text"]
    print("Got existing file...")
    if existing_content == future_meeting_text:
        print("File matches already! Nothing to do!")
        sys.exit()
    print("File disagree, need to replace")


print(f"New future meeting text for {BOLD}{file_path}{NC}:\n{BLUE}{future_meeting_text}{NC}")

response = input("Create new file in github? [Yn]")
if response and not response.lower().startswith("y"):
    print("Not creating.")
    sys.exit()

print(f"Existing repository oid: {BOLD}{existing_oid}{NC}")

payload = {
    "query": """mutation ($input:CreateCommitOnBranchInput!) {
                createCommitOnBranch(input: $input) { commit { url } } }""",
    "variables": {
        "input": {
            "branch": {"repositoryNameWithOwner": f"{repo_user}/{repo_name}", "branchName": f"{repo_branch}"},
            "expectedHeadOid": existing_oid,
            "message": {"headline": "Future meeting"},
            "fileChanges": {
                "additions": [
                    {
                        "path": file_path,
                        "contents": base64.b64encode(future_meeting_text.encode()).decode(),
                    }
                ]
            },
        }
    },
}

resp = requests.request(
    "POST",
    "https://api.github.com/graphql",
    headers={"Authorization": f"bearer {settings.GITHUB_TOKEN}"},
    json=payload,
)

if not resp.ok:
    sys.exit("Error: " + resp.text)

print(f"Created {BLUE}{resp.json()['data']['createCommitOnBranch']['commit']['url']}")
