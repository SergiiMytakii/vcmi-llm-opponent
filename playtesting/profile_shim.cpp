// Development-only macOS profile isolation. Python/Codex keep their real HOME.
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <mach-o/dyld.h>

static bool gameProcess()
{
    char executable[4096];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0)
        return false;
    auto base = std::strrchr(executable, '/');
    base = base ? base + 1 : executable;
    return std::strcmp(base, "vcmiclient") == 0 || std::strcmp(base, "vcmiserver") == 0;
}

static char * playtestGetenv(const char * name)
{
    if (std::strcmp(name, "HOME") == 0 && gameProcess())
        if (auto profile = getenv("VCMI_PLAYTEST_PROFILE"))
            return profile;
    return getenv(name);
}

__attribute__((used)) static const struct { const void * replacement; const void * original; } interpose
__attribute__((section("__DATA,__interpose"))) = {(const void *)&playtestGetenv, (const void *)&getenv};

__attribute__((constructor)) static void announce()
{
    if (gameProcess())
        std::fprintf(stderr, "PLAYTEST_PROFILE %s\n", getenv("VCMI_PLAYTEST_PROFILE") ? getenv("VCMI_PLAYTEST_PROFILE") : "MISSING");
}
