class SettlementJob
  def perform
    ApplicationRecord.transaction do
      LedgerEntry.create!(event: "settlement")
      Account.update_all(active: true)
    end
  end
end
