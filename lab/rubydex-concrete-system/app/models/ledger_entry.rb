class LedgerEntry < ApplicationRecord
  self.table_name = "ledger_entries"

  def persist!
    true
  end
end
