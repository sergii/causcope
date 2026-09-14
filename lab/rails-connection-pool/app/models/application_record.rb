class ApplicationRecord < ActiveRecord::Base
  primary_abstract_class

  if Rails.env.multi_database?
    connects_to database: {
      writing: :primary,
      reading: :replica
    }
  end
end
