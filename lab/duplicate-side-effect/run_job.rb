# frozen_string_literal: true

require "json"
require_relative "app/jobs/capture_payment_job"

payment_id, job_id, endpoint, trace_id, span_id, timeout_seconds = ARGV
abort("usage: run_job.rb PAYMENT_ID JOB_ID ENDPOINT TRACE_ID SPAN_ID TIMEOUT_SECONDS") unless timeout_seconds

begin
  result = CapturePaymentJob.new.perform(
    payment_id,
    job_id: job_id,
    endpoint: endpoint,
    trace_id: trace_id,
    span_id: span_id,
    timeout_seconds: Float(timeout_seconds)
  )
  puts JSON.generate({ outcome: "success", result: result })
rescue StandardError => error
  warn JSON.generate({ outcome: "error", error: error.class.name, message: error.message })
  exit 2
end
