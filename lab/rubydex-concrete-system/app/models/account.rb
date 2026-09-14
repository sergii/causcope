class Account < ApplicationRecord
  self.table_name = "accounts"

  def touch!
    true
  end
end
