#!/bin/sh
# Shared identity guard for this repository.
# Refuses to proceed unless the commit identity and remote belong to Thrya29.

EXPECTED_NAME="Thrya29"
EXPECTED_EMAIL="119743916+Thrya29@users.noreply.github.com"
EXPECTED_REMOTE_SUFFIX="github.com/Thrya29/SpendWise-AI-an-Adaptive-Purchase-Planning-and-Financial-Resilience-Engine.git"
FORBIDDEN_PATTERN='thrya-jane|janeaerospace'

fail() {
  echo "" >&2
  echo "BLOCKED by .githooks guard: $1" >&2
  echo "Fix the repo-local git config before retrying. Nothing was committed/pushed." >&2
  exit 1
}

check_identity() {
  name="$(git config user.name)"
  email="$(git config user.email)"
  [ "$name" = "$EXPECTED_NAME" ] || fail "user.name is '$name', expected '$EXPECTED_NAME'"
  [ "$email" = "$EXPECTED_EMAIL" ] || fail "user.email is '$email', expected '$EXPECTED_EMAIL'"
  for ident in "$(git var GIT_AUTHOR_IDENT)" "$(git var GIT_COMMITTER_IDENT)"; do
    echo "$ident" | grep -qiE "$FORBIDDEN_PATTERN" && fail "forbidden identity detected: $ident"
    echo "$ident" | grep -qF "$EXPECTED_EMAIL" || fail "author/committer email mismatch: $ident"
  done
  return 0
}

check_remote_url() {
  url="$1"
  case "$url" in
    *"$EXPECTED_REMOTE_SUFFIX") ;;
    *) fail "remote URL '$url' is not the Thrya29 SpendWise repository" ;;
  esac
  echo "$url" | grep -qiE "$FORBIDDEN_PATTERN" && fail "forbidden account in remote URL '$url'"
  return 0
}
