# Chapify user guide

Chapify lets you print a document without help from staff: you upload a PDF, choose how it
should be printed, pay the shown price and collect your printout when the print job is completed.

The application runs in a web browser. Locally it is at http://127.0.0.1:8000/.

## 1. Create an account and log in

1. Open Chapify. Every page first shows the log-in screen; choose **Create an account**.
2. Enter a username, your email address and a password (twice). Chapify rejects passwords that
   are too short, too common, only numbers or too similar to your username.
3. After registering you are logged in and see your **Home** page. Next time use **Log in**.

After logging in, Chapify decides from your account which pages you see: students get
**Print a document**, **Home** and **My requests**; administrators get the operations pages
described in the administrator guide. Both have **Account** (change your password) and
**Prices and help**.

If you enter a wrong password 5 times in a row, logging in is blocked for 15 minutes for your
username from that computer, even with the correct password. Wait and try again.

Your session ends when you close the browser or after 8 hours. Use **Log out** (bottom of the side menu, or under **Menu** on a phone) on shared computers.

## 2. Upload a document

1. Choose **Print a document**. The steps *Upload, Settings, Pay, Print* are shown at the top.
2. Drop your PDF on the upload area (or click it to choose a file) and press **Continue to settings**.

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

- **Copies** (1 to 100)
- **Color**: black and white or color
- **Paper size**: A4 or A3
- **Sides**: one-sided or double-sided

The estimated price updates as you choose. Press **Continue to payment** (the server calculates
the final price; **Not now** keeps the upload without creating a request). The price is

`pages x copies x 0.10 EUR x color (B/W 1.0, color 2.0) x paper (A4 1.0, A3 1.8) x sides (one-sided 1.0, double-sided 0.9)`

Example: a 10-page PDF, 2 copies, color, A4, one-sided costs 10 x 2 x 0.20 = **4.00 EUR**.
The full price list is on **Prices and help**.

## 4. Pay

1. On the payment page check the job slip and press **Pay … EUR**.
2. You are taken to the payment provider's page (**Chapify Pay**, a separate site). It runs in
   *test mode*: enter a **test card**, for example `4242 4242 4242 4242`, any name, any future
   expiry date (MM/YY) and any 3-digit security code, and press **Pay**. The list of test cards is
   under *Test card numbers* on that page; `4000 0000 0000 9995` shows a declined payment.
3. After a successful payment you return to Chapify automatically. After a declined payment the
   provider shows the reason; press **Return to the merchant**. **Cancel and return to Chapify**
   leaves without paying.

- **Paid**: your request becomes *Payment confirmed* and a print job is placed in the queue.
- **Declined**: your request becomes *Payment rejected*. You have not been charged. Press
  **Try payment again** or **Cancel request**.
- If Chapify says the payment service *has not confirmed the payment yet*, the request page
  updates by itself as soon as the provider reports the result.

Chapify never sees or stores card details. Until a payment is confirmed you can still
**Change settings** (the price is recalculated) or **Cancel request**.

## 5. Follow your print job

**Home** lists requests in progress and recently finished ones. **My requests** lists all of
them; choose **View** (or **Pay** for unpaid ones). The request page shows the job slip, a
progress timeline with times, the print job and the payment. Request statuses:

| Request status | Meaning |
|---|---|
| Awaiting payment | Created, not paid yet |
| Payment rejected | The gateway declined the payment; you may try again |
| Payment confirmed | Paid; the print job is queued or printing |
| Completed | Printed; collect your printout |
| Failed | The printer had a problem (for example a paper jam); staff can print it again |
| Cancelled | Cancelled by you, or not paid within 24 hours |

The print job shows *Queued*, *In progress*, *Completed* or *Failed* (with the reason).

**My requests** can be searched by request number or file name and filtered by status.

## 6. Your data

- You can only ever see your own requests and payments.
- Your uploaded file is deleted as soon as it has been printed or the request is cancelled.
  Unpaid requests are cancelled after 24 hours and their files deleted. If a print job fails,
  the file is kept for up to 24 hours so that staff can retry it.
- The request record (file name, settings, price, status) stays in your history.
