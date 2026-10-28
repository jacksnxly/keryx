#!/bin/sh
# Writes the commit list, the stat and the full diff of BASE..HEAD into one file for a reviewer and prints
# its path. Usage: package.sh OUT_DIR BASE HEAD   (run inside the repository)
set -eu
out_dir=$1 base=$2 head=$3
mkdir -p "$out_dir"
file="$out_dir/review-$(git rev-parse --short "$base")..$(git rev-parse --short "$head").diff"
{
  git log --format='%h %s' "$base..$head"
  echo
  git diff --stat "$base" "$head"
  echo
  git diff "$base" "$head"
} > "$file"
echo "$file"
