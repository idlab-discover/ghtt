# ghtt: helpers scripts for doing teacher stuff on GitHub

## Installation

[ghtt is available from the snap store.](https://snapcraft.io/ghtt)

```bash
sudo snap install ghtt
```

> Note: you might need to [install snapd](https://snapcraft.io/docs/installing-snapd), if it's not available on your system.

## `ghtt --help`

```txt

Usage: ghtt [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  assignment
  search      Searches repositories matching the query, prints the...
  util
```


## `ghtt search` helps you search GitHub for uploaded code

```txt
Usage: ghtt search [OPTIONS]

  Searches repositories matching the query, prints the matching
  repositories, name and email address of the last committer, and optionally
  emails this info using Mailgun.

  for more info on possible query patterns see
  https://developer.github.com/v3/search/#search-code

  Examples:
    * `./ghtt search -t "<github-token>" -u github.ugent.be -q "Allkit.h in:path"`
    * `./ghtt search -t "<github-token>" -u github.ugent.be -q "Allkit.h in:path" --mg-api-key <mailgun-api-key> --mg-domain <mailgun-url> --to <email-address>`

Options:
  -q, --query TEXT   Query to run. e.g. "Allkit.h in:path"   [required]
  --mg-api-key TEXT  Mailgun api key.
  --mg-domain TEXT   Mailgun domain name.
  --to TEXT          Email address to send alert to.
  -u, --url TEXT     URL to Github instance. Defaults to github.com.
  -t, --token TEXT   Github authentication token.
  --help             Show this message and exit.
```

## `ghtt assignment update-pr` helps you push code and create a pr to student repositories

```txt
Usage: ghtt update-pr [OPTIONS]

  Pushes updated code to a new branch on students repositories and creates a
  pr.

Options:
  -o, --organization TEXT  Github organization where student repos are located
                           [required]
  --branch TEXT            Name of the branch to create in students repos
                           [required]
  --title TEXT             Title of the pull request.  [required]
  --body TEXT              Body of the pull request (the message).  [required]
  -s, --source TEXT        Source directory
  -u, --url TEXT           URL to Github instance. Defaults to github.com.
  -t, --token TEXT         Github authentication token.
  --help                   Show this message and exit.
```

## Contributing

How to run the code without installing:

```shell
python3 -m ghtt
```
