class CheckoutService
  def call
    ApplicationRecord.transaction do
      Account.update_all(active: true)
      LedgerEntry.create!(event: "checkout")
    end
  end
end
