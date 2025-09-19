# pmaports docs

This is part of the postmarketOS handbook. The documentation is built using
[Antora](https://docs.antora.org/antora/latest/) since it allows pulling
information from different repositories, which is a great benefit on a
distributed project like ours. To build the documentation locally install
`nodejs` and `npm` from your favorite package manager, and from the top folder
of the repository run:

```sh
npm install antora
npx antora --clean antora-test.yml
```

After running the commands Antora should print the location of the generated
documentation.

Alternatively, you can use `pmbootstrap ci build-docs`.
