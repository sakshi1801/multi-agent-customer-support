"""Questions for the retrieval evaluation: (question, section(s) that answer it).

Written to share few words with the answer text, so keyword matching cannot just win by luck:
"Where can I follow my parcel?" should find "Shipping > Tracking your shipment".
A question about something the knowledge base does not cover has expected = None: the right
behaviour is to retrieve nothing, so the agent says it is not sure instead of making something up.
"""

CASES: list[tuple[str, list[str] | None]] = [
    # Shipping
    ("How many days until standard delivery arrives?", ["Shipping > Standard shipping"]),
    ("I need it fast, is there a quicker option?", ["Shipping > Express shipping"]),
    ("Do I have to pay for delivery on big purchases?", ["Shipping > Free shipping"]),
    ("How soon after ordering do you hand the parcel to the courier?", ["Shipping > Order processing time"]),
    ("Where can I follow my parcel?", ["Shipping > Tracking your shipment"]),
    ("Can you send to the UK?", ["Shipping > International shipping"]),
    ("What if I'm not home when the courier comes?", ["Shipping > Delivery attempts"]),
    ("My package is late, what now?", ["Shipping > Delayed deliveries"]),
    ("I typed the wrong address, can it be fixed?", ["Shipping > Changing the delivery address"]),
    # Returns
    ("Within how long can I send something back?", ["Returns > Return window"]),
    ("Does the item need its box to be returned?", ["Returns > Eligible items"]),
    ("Can I send back a gift card?", ["Returns > Non-returnable items"]),
    ("Where do I begin the return process?", ["Returns > How to start a return"]),
    ("Who pays for the postage when I send it back?", ["Returns > Return shipping label"]),
    (
        "When will the money for a returned item arrive?",
        ["Returns > Refund timing", "Payments > Refunds to your account"],
    ),
    ("Will the refund go to a different card?", ["Returns > Refund method"]),
    ("Can I swap my headphones for a different model?", ["Returns > Exchanges"]),
    ("The screen was cracked when it came", ["Returns > Damaged on arrival"]),
    ("You sent me a keyboard but I ordered a mouse", ["Returns > Wrong item received"]),
    # Orders
    ("Is it still possible to stop my order?", ["Orders > Cancelling an order"]),
    ("Can I add another item to an order I just placed?", ["Orders > Changing an order"]),
    ("What does 'processing' mean for my order?", ["Orders > Order statuses"]),
    ("I never got a confirmation mail", ["Orders > Order confirmation"]),
    ("I accidentally bought the same thing twice", ["Orders > Duplicate orders"]),
    # Payments
    ("Which cards can I use?", ["Payments > Accepted payment methods"]),
    ("At what moment does my bank take the money?", ["Payments > When you are charged"]),
    ("My payment didn't go through but I was debited", ["Payments > Failed payments"]),
    ("Can I get a GST bill?", ["Payments > Invoices and tax"]),
    ("Can I use two discount codes?", ["Payments > Promo codes"]),
    (
        "How long until a refund lands in my bank?",
        ["Payments > Refunds to your account", "Returns > Refund timing"],
    ),
    # Warranty
    ("How long is my laptop covered for defects?", ["Warranty > Warranty period"]),
    ("I spilled coffee on it, is that covered?", ["Warranty > What is not covered"]),
    ("How do I claim for a faulty device?", ["Warranty > Making a warranty claim"]),
    ("Does a replacement unit get a fresh warranty?", ["Warranty > Replacement items"]),
    # Account
    ("I can't remember my login password", ["Account > Resetting your password"]),
    ("I want to use a different email", ["Account > Changing your email address"]),
    ("Remove all my data from your system", ["Account > Deleting your account"]),
    ("Can other customers see my orders?", ["Account > Privacy"]),
    # Contact
    ("When can I phone someone?", ["Contact > Support hours"]),
    ("How quickly will a manager get back to me?", ["Contact > Response time for escalations"]),
    ("I'd like to speak with a real person", ["Contact > Talking to a human"]),
    # Not in the knowledge base: the right answer is to retrieve nothing
    ("What's the capital of France?", None),
    ("Recommend a good laptop under 50000", None),
    ("How do I fix my wifi router?", None),
    ("Tell me a joke", None),
    ("What's the weather today?", None),
    ("Who is the prime minister?", None),
    ("Do you sell gaming chairs?", None),
    ("Write me a poem about the monsoon", None),
    ("Is Bitcoin going up this week?", None),
]
