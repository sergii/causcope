Rails.application.routes.draw do
  get "/health", to: "pool#health"
  get "/status", to: "pool#status"
  get "/hold", to: "pool#hold"
  get "/work", to: "pool#work"
  get "/multi-pool", to: "pool#multi_pool"
end
