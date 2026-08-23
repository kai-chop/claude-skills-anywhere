# qwen-skilled -- start Qwen Code with your Claude skills actually loadable.
#
# Same workspace rule as gemini-skilled.ps1: the skill canon has to be inside the
# workspace or the body cannot be read.
#
# Auth: Qwen Code's own OAuth needs a browser. When no OAuth credentials exist yet,
# this falls back to an OpenAI-compatible endpoint using DASHSCOPE_API_KEY, set for
# the duration of this call only and restored afterwards -- leaving OPENAI_API_KEY
# in the environment makes every other tool on the machine talk to that provider
# with that key.
#
# Override: $env:SKILLS_CANON, $env:QWEN_BIN, $env:QWEN_BASE_URL, $env:QWEN_MODEL.

$canon = if ($env:SKILLS_CANON) { $env:SKILLS_CANON } else { Join-Path $HOME '.claude\skills' }
$bin = if ($env:QWEN_BIN) { $env:QWEN_BIN } else { 'qwen' }
$oauth = Join-Path $HOME '.qwen\oauth_creds.json'

if (Test-Path -LiteralPath $oauth) {
    & $bin --include-directories $canon @args
    exit $LASTEXITCODE
}

$key = $env:DASHSCOPE_API_KEY
if (-not $key -and $env:OS -eq 'Windows_NT') {
    # setx-registered values are not in the current process environment yet.
    $key = [Environment]::GetEnvironmentVariable('DASHSCOPE_API_KEY', 'User')
}
if (-not $key) {
    Write-Error "qwen-skilled: no $oauth and no DASHSCOPE_API_KEY. Run ``qwen`` once in a real terminal to log in, or set DASHSCOPE_API_KEY."
    exit 1
}

$names = 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_MODEL'
$saved = @{}
$code = 1   # never report success if we die before the CLI runs
foreach ($n in $names) { $saved[$n] = [Environment]::GetEnvironmentVariable($n) }
try {
    $env:OPENAI_API_KEY = $key
    $env:OPENAI_BASE_URL = if ($env:QWEN_BASE_URL) { $env:QWEN_BASE_URL } else { 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1' }
    $env:OPENAI_MODEL = if ($env:QWEN_MODEL) { $env:QWEN_MODEL } else { 'qwen3-coder-plus' }
    & $bin --auth-type openai --include-directories $canon @args
    $code = $LASTEXITCODE
} finally {
    foreach ($n in $names) {
        if ($null -eq $saved[$n]) { Remove-Item -LiteralPath "Env:$n" -ErrorAction SilentlyContinue }
        else { Set-Item -LiteralPath "Env:$n" -Value $saved[$n] }
    }
}
exit $code
