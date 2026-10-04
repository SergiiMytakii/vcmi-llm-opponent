"""Build the pinned Windows 11 x64 developer distribution in a fresh directory."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=ROOT / '.build/windows')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        parser.error('run on Windows x64 in an x64 MSVC v142 (14.29) Developer PowerShell')
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    compiler = shutil.which('cl')
    if not compiler:
        parser.error('MSVC is not on PATH; open an x64 v142 Developer PowerShell')
    compiler_version = subprocess.run([compiler], capture_output=True)
    if b'19.29.' not in compiler_version.stdout + compiler_version.stderr:
        parser.error('select MSVC v142 / compiler 19.29 to match the pinned dependency profile')
    vs_major = os.environ.get('VisualStudioVersion', '').split('.')[0]
    if not vs_major.isdigit():
        parser.error('VisualStudioVersion is missing; use a Visual Studio Developer PowerShell')
    for line in (ROOT / 'requirements-build.txt').read_text().splitlines():
        package, version = line.split('==')
        if importlib.metadata.version(package) != version:
            parser.error('install requirements-build.txt in this Python environment first')
    programs = {}
    for name in ('cmake', 'conan'):
        executable = Path(sys.executable).parent / (name + '.exe')
        if not executable.is_file():
            parser.error('run with .venv\\Scripts\\python.exe after installing requirements-build.txt')
        programs[name] = str(executable)
    pin = json.loads((ROOT / 'engine/version.json').read_text())
    work = args.work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'CONAN_HOME': str(work / 'conan'),
           'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')}
    commands = []
    with (work / 'build.log').open('w', encoding='utf-8') as log:
        def run(command, cwd=ROOT):
            commands.append([str(arg) for arg in command])
            log.write('\n' + subprocess.list2cmdline(commands[-1]) + '\n')
            log.flush()
            subprocess.run(commands[-1], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)

        source = work / 'vcmi'
        run([sys.executable, ROOT / 'scripts/prepare_engine.py', source])
        archive = work / 'dependencies-windows-x64.txz'
        url = ('https://github.com/vcmi/vcmi-dependencies/releases/download/'
               + pin['dependencies_release'] + '/dependencies-windows-x64.txz')
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as response, archive.open('xb') as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != pin['windows_dependencies_sha256']:
            raise ValueError('dependency SHA-256 mismatch; archive was not restored')
        run([programs['conan'], 'profile', 'detect'])
        run([programs['conan'], 'cache', 'restore', archive])
        generated = work / 'conan-generated'
        run([programs['conan'], 'install', '.', '--output-folder=' + str(generated), '--build=never',
             '--profile=dependencies/conan_profiles/msvc-x64',
             '--conf=tools.cmake.cmaketoolchain:generator=Ninja',
             '--conf=tools.microsoft.msbuild:vs_version=' + vs_major], cwd=source)
        toolchain = generated / 'conan_toolchain.cmake'
        build = work / 'build'
        run([programs['cmake'], '-S', source, '-B', build, '-G', 'Ninja',
             '-DCMAKE_TOOLCHAIN_FILE=' + toolchain.as_posix(), '-DCMAKE_BUILD_TYPE=Release',
             *['-DENABLE_' + option + '=OFF' for option in
               ('LAUNCHER', 'EDITOR', 'TEST', 'MMAI', 'DISCORD', 'INNOEXTRACT', 'CCACHE')]])
        run([programs['cmake'], '--build', build, '--target', 'vcmiclient', 'vcmiserver', '-j', args.jobs])
        runtime = work / 'runtime'
        run([programs['cmake'], '--install', build, '--prefix', runtime, '--config', 'Release'])
        transport = work / 'transport'
        run([programs['cmake'], '-S', ROOT / 'tests', '-B', transport, '-G', 'Ninja',
             '-DCMAKE_TOOLCHAIN_FILE=' + toolchain.as_posix(), '-DCMAKE_BUILD_TYPE=Release'])
        run([programs['cmake'], '--build', transport, '-j', args.jobs])
        # The real native driver needs the same Conan DLL directories as VCMI.
        dll_dirs = {str(Path(line).parent) for line in (generated / '_runtime_libs.txt').read_text().splitlines() if line}
        env['PATH'] = os.pathsep.join([str(runtime), *sorted(dll_dirs), env['PATH']])
        env['EXCHANGE_DRIVER'] = str(transport / 'exchange-driver.exe')
        env['FAKE_CODEX_DRIVER'] = str(transport / 'fake-codex-driver.exe')
        env['VCMI_NATIVE_PROFILE_ENGINE'] = str(runtime / 'VCMI_client.exe')
        env['PYTHONUTF8'] = '1'
        run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
        (work / 'build-evidence.json').write_text(json.dumps({
            'engine_pin': pin, 'compiler': compiler_version.stderr.decode(errors='replace'),
            'commands': commands, 'runtime': str(runtime), 'tests': 'passed',
            'gameplay': 'not checked',
        }, indent=2), encoding='utf-8')
    print('Build and subprocess tests passed. Runtime:', runtime)
    print('Gameplay and Windows isolation still need the checks in docs/playing.md.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as error:
        print('build_windows:', error, file=sys.stderr)
        raise SystemExit(1)
