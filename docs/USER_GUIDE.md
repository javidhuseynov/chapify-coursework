# Chapify user guide

Chapify lets you print a document without help from staff: you upload a PDF, choose how it
should be printed, pay the shown price and collect your printout when the print job is completed.

The application runs in a web browser. Locally it is at http://127.0.0.1:8000/.

## 1. Create an account and log in

1. Open Chapify and choose **Register**.
2. Enter a username, your email address and a password (twice). Chapify rejects passwords that
   are too short, too common, only numbers or too similar to your username.
3. After registering you are logged in. Next time use **Login**.

If you enter a wrong password 5 times in a row, logging in is blocked for 15 minutes for your
username from that computer, even with the correct password. Wait and try again.

Your session ends when you close the browser or after 8 hours. Use **Logout** on shared computers.

## 2. Upload a document

1. Choose **New Request**.
2. Select your file and press **Continue to print settings**.

Rules for the file:

| Rule | Why |
|---|---|
| PDF only | The number of pages can be counted exactly. Save Word documents as PDF first. |
| Maximum 5 MB | Keeps uploads fast. |
| Maximum 500 pages | Very large jobs need staff assistance. |
| No password protection | Chapify must be able to open the file to print it. |

If the file is rejected, the page tells you why (for example "The file is not a valid PDF
document" for a renamed photo).

## 3. Choose print settings and see the price

Chapify shows the number of pages it counted in your PDF (you cannot change it). Choose:

- **Copies**
- **Colour mode**: black-and-white or colour
- **Paper format**: A4 or A3
- **Duplex mode**: one-sided or double-sided

Press **Calculate price and continue**. The price is

`pages x copies x 0.10 EUR x colour (B/W 1.0, colour 2.0) x paper (A4 1.0, A3 1.8) x duplex (one-sided 1.0, double-sided 0.9)`

Example: a 10-page PDF, 2 copies, colour, A4, one-sided costs 10 x 2 x 0.20 = **4.00 EUR**.

## 4. Pay

1. On the payment page check the summary and press **Pay**.
2. You are taken to the payment gateway page (**Chapify Pay**). In this prototype the gateway is
   in *test mode*: there is no card form; press **Approve payment** (or **Decline payment** to
   try the declined case).
3. You return to Chapify automatically.

- **Approved**: your request becomes *Payment confirmed* and a print job is placed in the queue.
- **Declined**: your request becomes *Payment rejected*. Press **Try payment again** or cancel.

Chapify never sees or stores card details. Until a payment is confirmed you can still
**Edit** the settings (the price is recalculated) or **Cancel** the request.

## 5. Follow your print job

Open **My History** and choose **View** next to a request. You see:

| Request status | Meaning |
|---|---|
| Awaiting payment | Created, not paid yet |
| Payment rejected | The gateway declined the payment; you may try again |
| Payment confirmed | Paid; the print job is queued or printing |
| Completed | Printed; collect your printout |
| Failed | The printer had a problem; staff can retry the job |
| Cancelled | Cancelled by you, or not paid within 24 hours |

The print job shows *Queued*, *In progress*, *Completed* or *Failed* (with the reason).

**My History** can be searched by request number or file name and filtered by status.

## 6. Your data

- You can only ever see your own requests and payments.
- Your uploaded file is deleted as soon as it has been printed or the request is cancelled.
  Unpaid requests are cancelled after 24 hours and their files deleted. If a print job fails,
  the file is kept for up to 24 hours so that staff can retry it.
- The request record (file name, settings, price, status) stays in your history.
