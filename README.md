# gh-exam: helper script for running an exam on the UGent Github

1. `gh-exam create` maakt voor elke student een private repository aan op basis van opgavecode. De student krijgt er initieel nog geen toegang toe zodat we dit kunnen doen bv een dag voor het examen.
2. Wanneer het examen begint geven we de studenten dan toegang tot hun repository met `gh-exam grant`.
3. Wanneer een student klaar is geeft hij zijn papieren opgave af en verwijdert de examenbegeleider manueel de toegang van de student op de repository. Op die manier kan niemand naar buiten gaan terwijl ze nog toegang hebben tot hun repository.

*`gh-exam remove-grant` kan uitgevoerd worden om alle studenten in één keer de toegang tot hun repository te ontzeggen.*

Het idee is dan dat de studenten hun eigen repo clonen bij het starten van het examen. In die repo staat een Code Workspace, door die te openen starten ze visual studio code direct in de juiste map. Ze maken hun examen en als ze klaar zijn kunnen ze gewoon vanuit visual studio code pushen en zelf op github.ugent.be controleren of de juiste code er effectief staat. De master branch is beveiligd tegen een force push, ze kunnen hun geschiedenis dus niet herschrijven.

Als we willen kunnen we door middel van github triggers een scriptje laten lopen dat bij iedere push controleert of ze wel de correcte code ingedient hebben, we zouden zelfs al kunnen kijken of de code compileert bijvoorbeeld.


## Creating student repositories

```bash
./gh-exam create -o <organization-name> -t <github-token> -s <path/to/assignment/repository>
```

This command creates a private repository for each student named `examen-<student-username>`.

* Each repository is located in the organization specified by `-o <organization-name>`
* Each repository contains the code in the git repository at `<path/to/assignment/repository>`
* Each repository is protected against force pushes. (rewrites of the git history)
* This command **does not** grant the students access to the repository, use the `grant` command for that.


## Granting students push-access to their repositories

```bash
./gh-exam grant -o <organization-name> -t <github-token>
```

This command grants each student push access to their repository in the specified organization.


## Removing students push-access to their repositories

```bash
./gh-exam remove-grant -o <organization-name> -t <github-token>
```

This command removes students' push access to their repository and cancels any open invitation for that student.
