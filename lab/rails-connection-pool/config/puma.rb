thread_count = Integer(ENV.fetch("RAILS_MAX_THREADS", "5"))
threads thread_count, thread_count
workers 0
port Integer(ENV.fetch("PORT", "4567"))
environment ENV.fetch("RAILS_ENV", "production")
