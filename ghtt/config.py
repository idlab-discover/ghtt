#!/usr/bin/env python3
import csv
import re
from typing import List, Dict, Optional
from urllib.parse import urlparse

from jinja2 import Template
import yaml


class Student:
    username: str
    comment: str
    record: dict
    group: str

    def __init__(self, username: str):
        self.username = username
        self.fullname = ""
        self.email = ""
        self.comment = ""
        self.mentor_username = None
        self.record = {}
        self.group = None

    def __str__(self):
        return "Student '{}' ('{}') [{}] {}".format(
            self.username, self.comment, self.group, self.record)


class StudentRepo:
    def __init__(self, name: str):
        self.name = name
        self.comment = ""
        self.students: List[Student] = []
        self.mentors: List[Student] = []
        self.organization = ""


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
    return default


def get_students(usernames: List[str] = [], groups: List[str] = []) -> List[Student]:
    students = []
    student_config = get("students", None)
    if not student_config:
        return students
    mapping = student_config['field-mapping']
    try:
        with open(student_config["source"]) as f:
            rows = csv.DictReader(f, delimiter=',', quotechar='|')
            for row in rows:
                student = Student(row[mapping['username']], )
                student.username = student.username.strip("#")
                if usernames and student.username not in usernames:
                    continue
                student.record = row
                student.comment = Template(mapping["comment"]).render(record=student.record)
                student.fullname = Template(mapping["fullname"]).render(record=student.record)
                student.email = row[mapping['email']]
                if mapping.get("group"):
                    student.group = student.record[mapping['group']]
                    student.group = student.group.lower()
                    student.group = re.sub("[^0-9a-z]+", "-", student.group)
                    if student.group == "":
                        student.group = None
                    if groups and student.group not in groups:
                        continue
                students.append(student)
    except FileNotFoundError:
        print("The student database '{}' was not found".format(student_config['source']))
        return students
    return students


def get_mentors() -> List[Student]:
    """
    Assumes config contains:
     mentors:
        - fullname: Person 1
          username: pers1
          email: pers1@example.com
        - fullname: Person 2
          username: pers2
          email: pers2@example.com
    """
    mentors_config = get("mentors", None)
    if not mentors_config:
        return []
    mentors = []
    for m in mentors_config:
        mentor = Student(m.get('username'))
        mentor.fullname = m.get('fullname')
        mentor.email = m.get('email')
        mentors.append(mentor)
    return mentors


def get_organization() -> str:
    return urlparse(get("url", None)).path.rstrip("/").rsplit("/", 1)[-1]


def get_repos(students: List[Student], mentors: Optional[List[Student]] = None) -> Dict[str, StudentRepo]:
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
        repo.comment = ", ".join([s.comment for s in repo.students])
        repo.organization = organization
        repo.mentors = mentors
        repos[repo.name] = repo
    return repos
