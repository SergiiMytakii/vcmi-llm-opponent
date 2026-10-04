#include "ProcessExchange.h"

#include <boost/asio.hpp>
#include <boost/process.hpp>
#include <boost/process/async_pipe.hpp>
#include <array>
#include <functional>
#include <thread>
#include <system_error>
#ifdef __APPLE__
#include <cerrno>
#include <fcntl.h>
#endif
#ifdef _WIN32
#include <boost/locale/encoding_utf.hpp>
#include <boost/process/extend.hpp>
#include <windows.h>
#endif

namespace externalai
{
#ifdef _WIN32
struct ResumeInJob : boost::process::extend::handler
{
	template<class Executor> void on_setup(Executor & exec) const
	{
		exec.creation_flags |= CREATE_SUSPENDED;
	}
	template<class Executor> void on_success(Executor & exec) const
	{
		if(ResumeThread(exec.proc_info.hThread) == static_cast<DWORD>(-1))
			exec.set_error(std::error_code(GetLastError(), std::system_category()), "ResumeThread failed");
	}
	template<class Executor> void on_error(Executor & exec, const std::error_code &) const
	{
		if(exec.proc_info.hProcess)
			TerminateProcess(exec.proc_info.hProcess, 1);
	}
};
#endif

Reply exchange(const std::string & executable, const std::vector<std::string> & arguments,
	const std::string & input, std::chrono::milliseconds timeout, const std::atomic<bool> & cancelled)
{
	namespace bp = boost::process;
	namespace asio = boost::asio;
	Reply reply;
	if(cancelled)
		return {{}, "cancelled"};
	if(input.size() > 256 * 1024)
		return {{}, "request too large"};
	const auto deadline = std::chrono::steady_clock::now() + timeout;
	try
	{
		asio::io_context io;
		bp::async_pipe source(io), sink(io);
		#ifdef __APPLE__
		if(::fcntl(source.native_sink(), F_SETNOSIGPIPE, 1) == -1)
			throw std::system_error(errno, std::generic_category(), "protect controller stdin");
		#endif
		bp::group group;
		#ifdef _WIN32
		std::vector<std::wstring> wideArguments;
		for(const auto & argument : arguments)
			wideArguments.push_back(boost::locale::conv::utf_to_utf<wchar_t>(argument));
		bp::child child(boost::locale::conv::utf_to_utf<wchar_t>(executable), bp::args(wideArguments), group, ResumeInJob{},
			bp::std_in < source, bp::std_out > sink, bp::std_err > bp::null);
		#else
		bp::child child(executable, bp::args(arguments), group,
			bp::std_in < source, bp::std_out > sink, bp::std_err > bp::null);
		#endif
		asio::steady_timer timer(io);
		std::array<char, 4096> buffer{};
		bool closed = false;
		bool exited = false;
		auto stop = [&]()
		{
			std::error_code error;
			group.terminate(error);
			boost::system::error_code pipeError;
			source.close(pipeError);
			sink.close(pipeError);
			timer.cancel();
		};
		std::function<void()> read;
		read = [&]()
		{
			sink.async_read_some(asio::buffer(buffer), [&](const boost::system::error_code & error, std::size_t count)
			{
				if(reply.output.size() + count > 8192)
				{
					reply.error = "reply too large";
					stop();
					return;
				}
				reply.output.append(buffer.data(), count);
				if(!error)
					read();
				else
				{
					closed = true;
					if(error != asio::error::eof && reply.error.empty())
						reply.error = "reply pipe failed";
				}
			});
		};
		read();
		asio::async_write(source, asio::buffer(input), [&](const boost::system::error_code & error, std::size_t)
		{
			if(error && reply.error.empty())
				reply.error = "request pipe failed";
			boost::system::error_code closeError;
			source.close(closeError);
		});
		std::function<void()> poll;
		poll = [&]()
		{
			timer.expires_after(std::chrono::milliseconds(20));
			timer.async_wait([&](const boost::system::error_code & error)
			{
				if(error)
					return;
				if(cancelled || std::chrono::steady_clock::now() >= deadline)
				{
					reply.error = cancelled ? "cancelled" : "timeout";
					stop();
					return;
				}
				if(!exited && !child.running())
				{
					exited = true;
					if(child.exit_code() != 0)
						reply.error = child.exit_code() == 75 ? "timeout" : "controller exited unsuccessfully";
					std::error_code groupError;
					group.terminate(groupError); // Close pipes inherited by surviving descendants.
				}
				if(exited && closed)
					return;
				poll();
			});
		};
		poll();
		io.run();
		const auto reapDeadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(200);
		while(child.running() && std::chrono::steady_clock::now() < reapDeadline)
			std::this_thread::sleep_for(std::chrono::milliseconds(5));
		if(child.running())
			reply.error = "controller cleanup did not complete";
	}
	catch(const std::exception & error)
	{
		reply.error = error.what();
	}
	if(!reply.error.empty())
		reply.output.clear();
	return reply;
}
}
