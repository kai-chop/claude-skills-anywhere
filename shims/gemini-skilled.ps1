# gemini-skilled -- start Gemini CLI with your Claude skills actually loadable.
#
# Linking a skill into ~/.gemini/skills makes `gemini skills list` show it as
# [Enabled], but activating it fails with "Path not in workspace": the CLI refuses
# to read files outside the workspace, and both ~/.gemini/skills and the canon are
# outside it. Copying instead of linking does not help -- the copy is outside too.
# Adding the canon root to the workspace is what makes the body readable.
#
# Measured 2026-08-24 with a controlled pair: same prompt, flag present = the model
# quotes the skill body and exits 0; flag absent = "Path not in workspace".
#
# Override the canon with $env:SKILLS_CANON, the binary with $env:GEMINI_BIN.

$canon = if ($env:SKILLS_CANON) { $env:SKILLS_CANON } else { Join-Path $HOME '.claude\skills' }
$bin = if ($env:GEMINI_BIN) { $env:GEMINI_BIN } else { 'gemini' }

& $bin --include-directories $canon @args
exit $LASTEXITCODE
