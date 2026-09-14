# frozen_string_literal: true

require "json"
require "net/http"
require "uri"

class PaymentsClient
  def self.charge(payment_id, job_id:, endpoint:, trace_id:, span_id:, timeout_seconds:)
    uri = URI(endpoint)
    request = Net::HTTP::Post.new(uri)
    request["Content-Type"] = "application/json"
    request["X-Causcope-Job-Id"] = job_id
    request["X-Causcope-Trace-Id"] = trace_id
    request["X-Causcope-Span-Id"] = span_id
    request.body = JSON.generate({ payment_id: payment_id })

    Net::HTTP.start(
      uri.host,
      uri.port,
      open_timeout: timeout_seconds,
      read_timeout: timeout_seconds
    ) do |http|
      response = http.request(request)
      raise "payments provider returned HTTP #{response.code}" unless response.is_a?(Net::HTTPSuccess)

      JSON.parse(response.body)
    end
  end
end
