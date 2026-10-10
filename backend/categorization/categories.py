from typing import Literal, get_args

# The expense categories the classifier can predict. A receipt it isn't confident about gets none (null).
Category = Literal[
    "Meals",
    "Groceries",
    "Travel",
    "Transport",
    "Office Supplies",
    "Software & Subscriptions",
    "Utilities & Phone",
]
CATEGORIES: tuple[Category, ...] = get_args(Category)
