#!/usr/bin/env python3
#%%
import csv
import re
from typing import List, Dict, Optional
from urllib.parse import urlparse

from jinja2 import Template
import yaml


class Person:
    username: str
    comment: str
    record: dict
    group: str
    groups: List[str]

    def __init__(self, username: str):
        self.username = username
        self.comment = ""
        self.record = {}
        self.group = None
        self.groups = []

    def __str__(self):
        return "Student '{}' ('{}') Group: '{}'  Groups: '{}'  Record: {}".format(
            self.username, self.comment, self.group, self.groups, self.record)


class StudentRepo:
    def __init__(self, name: str):
        self.name = name
        self.comment = ""
        self.students: List[Person] = []
        self.mentors: List[Person] = []
        self.organization = ""
        self.group = None


def get(keypath: str, default):
    try:
        with open("./ghtt.yaml") as f:
            config = yaml.safe_load(f)
        item = config
        for key in keypath.split("."):
            item = item[key]
        return item
    except FileNotFoundError:
        print("ERROR: The config file `ghtt.yaml` was not found in the current directory.")
        exit(1)
    except KeyError:
        pass
    return default


def get_persons(persons_config: dict, usernames: List[str] = [], groups: List[str] = []) -> List[Person]:
    persons = []
    if not persons_config:
        return persons
    mapping = persons_config['field-mapping']
    try:
        with open(persons_config["source"]) as f:
            rows = csv.DictReader(f, delimiter=',', quotechar='"')
            for row in rows:
                person = Person(row[mapping['username']], )
                person.username = person.username.strip("#")
                if usernames and person.username not in usernames:
                    continue
                person.record = row
                person.comment = Template(mapping["comment"]).render(record=person.record)
                if mapping.get("group"):
                    person.group = person.record[mapping['group']]
                    person.group = canonize_group(person.group)
                    if person.group == "":
                        person.group = None
                    if groups and person.group not in groups:
                        continue
                if mapping.get("groups"):
                    person.groups = person.record[mapping['groups']].split(",")
                    if person.groups == "":
                        person.groups = []
                    person.groups = [group.strip() for group in person.groups]
                    person.groups = [canonize_group(group) for group in person.groups]
                persons.append(person)
    except FileNotFoundError:
        print("The student database '{}' was not found".format(persons_config['source']))
        return persons
    return persons


def get_students(usernames: List[str] = [], groups: List[str] = []) -> List[Person]:
    student_config = get("students", None)
    return get_persons(student_config, usernames, groups)


def get_mentors(usernames: List[str] = [], groups: List[str] = []) -> List[Person]:
    config = get("mentors", None)
    return get_persons(config, usernames, groups)


def get_organization() -> str:
    return urlparse(get("url", None)).path.rstrip("/").rsplit("/", 1)[-1]


def get_repos(students: List[Person], mentors: Optional[List[Person]] = None) -> Dict[str, StudentRepo]:
    if mentors is None:
        mentors = []
    repos = {}
    student_config = get("students", None)
    if not student_config:
        return students
    mapping = student_config['field-mapping']

    organization = get_organization()

    for student in students:
        if mapping.get("group"):
            if not student.group:
                print("{} is not a member of any group; skipping.".format(student.username))
                continue
            reponame = "{}-{}".format(
                organization,
                student.group
            )
            repo = repos.get(reponame, StudentRepo(reponame))
        else:
            repo = StudentRepo("{}-{}".format(
                organization,
                student.username
            ))
        repo.students.append(student)
        repo.group = student.group
        repo.comment = ", ".join([s.comment for s in repo.students])
        repo.organization = organization
        repo.mentors = [m for m in mentors if repo.group in m.groups]
        repos[repo.name] = repo
    return repos




# import os
# os.chdir("/home/merlijn/PHD/SYSPROG/project/")
# students = get_students(groups=["project-groep-test"])
# for student in students:
#     print(student)

# print()
# print()

# mentors = get_mentors()
# for student in mentors:
#     print(student)
