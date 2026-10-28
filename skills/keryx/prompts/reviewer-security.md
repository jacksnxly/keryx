- Security pass: rank the changed files by risk (auth, money, privacy, outside calls), read what the change removed
  (`git log -p`, blame on the deleted lines), and name who could misuse each risky path and how. Report each misuse
  as a finding in the shape below.
