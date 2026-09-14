# frozen_string_literal: true

require_relative "../services/payments_client"

class CapturePaymentJob
  def self.sidekiq_options(**_options); end

  sidekiq_options retry: 3

  def perform(payment_id, job_id:, endpoint:, trace_id:, span_id:, timeout_seconds:)
    PaymentsClient.charge(
      payment_id,
      job_id: job_id,
      endpoint: endpoint,
      trace_id: trace_id,
      span_id: span_id,
      timeout_seconds: timeout_seconds
    )
  end
end
