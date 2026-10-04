// Native test CLI: run the Python Codex fixture without a shell or a detached child.
#include <cstdlib>
#include <iostream>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#include <string>

static std::wstring quote(const std::wstring & argument)
{
	std::wstring result = L"\"";
	std::size_t slashes = 0;
	for(wchar_t character : argument)
	{
		if(character == L'\\')
		{
			++slashes;
			continue;
		}
		result.append(character == L'"' ? slashes * 2 + 1 : slashes, L'\\');
		result += character;
		slashes = 0;
	}
	result.append(slashes * 2, L'\\');
	return result + L'"';
}

int wmain(int argc, wchar_t ** argv)
{
	const auto * python = _wgetenv(L"CODEX_TEST_PYTHON");
	const auto * script = _wgetenv(L"CODEX_TEST_SCRIPT");
	if(!python || !script)
		return 125;
	std::wstring command = quote(python) + L" " + quote(script);
	for(int i = 1; i < argc; ++i)
		command += L" " + quote(argv[i]);
	HANDLE job = CreateJobObjectW(nullptr, nullptr);
	if(!job)
		return 125;
	JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
	limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
	if(!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
	{
		CloseHandle(job);
		return 125;
	}
	STARTUPINFOW startup{};
	startup.cb = sizeof(startup);
	startup.dwFlags = STARTF_USESTDHANDLES;
	startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
	startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
	startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
	PROCESS_INFORMATION process{};
	if(!CreateProcessW(python, command.data(), nullptr, nullptr, TRUE, CREATE_SUSPENDED,
		nullptr, nullptr, &startup, &process))
	{
		CloseHandle(job);
		return 125;
	}
	DWORD code = 125;
	if(AssignProcessToJobObject(job, process.hProcess)
		&& ResumeThread(process.hThread) != static_cast<DWORD>(-1))
	{
		WaitForSingleObject(process.hProcess, INFINITE);
		GetExitCodeProcess(process.hProcess, &code);
	}
	else
	{
		TerminateProcess(process.hProcess, 125);
		WaitForSingleObject(process.hProcess, INFINITE);
	}
	CloseHandle(process.hThread);
	CloseHandle(process.hProcess);
	CloseHandle(job);
	return static_cast<int>(code);
}
#else
#include <unistd.h>
int main(int argc, char ** argv)
{
	const auto * python = std::getenv("CODEX_TEST_PYTHON");
	const auto * script = std::getenv("CODEX_TEST_SCRIPT");
	if(!python || !script)
		return 125;
	std::vector<char *> arguments{const_cast<char *>(python), const_cast<char *>(script)};
	arguments.insert(arguments.end(), argv + 1, argv + argc);
	arguments.push_back(nullptr);
	execv(python, arguments.data());
	return 125;
}
#endif
