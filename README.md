## API Testing Documentation

This section describes the tested REST API endpoints of the Chapify prototype.
The API was tested using `curl` commands from PowerShell.

### 1. Obtain Authentication Token

Endpoint:

```http
POST /api/auth/token/
```

Example request:

```bash
curl.exe -X POST http://127.0.0.1:8000/api/auth/token/ ^
  -d "username=testuser" ^
  -d "password=testpassword"
```

Example response:

```json
{
  "token": "YOUR_TOKEN_HERE"
}
```

The returned token must be used in the `Authorization` header for protected API requests.

---

### 2. View Current User Print Requests

Endpoint:

```http
GET /api/my/requests/
```

Example request:

```bash
curl.exe -H "Authorization: Token YOUR_TOKEN_HERE" ^
  http://127.0.0.1:8000/api/my/requests/
```

Example response:

```json
[
  {
    "id": 10,
    "document": {
      "id": 10,
      "file_name": "test.txt",
      "file_type": "txt",
      "file_size": 26,
      "validation_status": "VALID"
    },
    "settings": {
      "copies": 2,
      "color_mode": "COLOR",
      "paper_format": "A4",
      "duplex_mode": true
    },
    "total_price": "0.40",
    "status": "PENDING_PAYMENT"
  }
]
```

This endpoint allows an authenticated user to view their own submitted print requests.

---

### 3. Create a New Print Request with File Upload

Endpoint:

```http
POST /api/requests/create/
```

Example request:

```bash
curl.exe -H "Authorization: Token YOUR_TOKEN_HERE" ^
  -X POST http://127.0.0.1:8000/api/requests/create/ ^
  -F "document=@test.txt" ^
  -F "copies=2" ^
  -F "color_mode=COLOR" ^
  -F "paper_format=A4" ^
  -F "duplex_mode=true"
```

Example response:

```json
{
  "message": "Print request created successfully.",
  "request_id": 10,
  "document_status": "VALID",
  "payment_status": "PENDING",
  "print_request_status": "PENDING_PAYMENT"
}
```

This endpoint creates a new print request, validates the uploaded document, stores the selected print settings, calculates the price, and prepares the request for payment.

---

### 4. Confirm Payment for a Print Request

Endpoint:

```http
POST /api/requests/<request_id>/payment/confirm/
```

Example request:

```bash
curl.exe -H "Authorization: Token YOUR_TOKEN_HERE" ^
  -X POST http://127.0.0.1:8000/api/requests/10/payment/confirm/
```

Example response:

```json
{
  "message": "Payment confirmed and print job created.",
  "payment_id": 9,
  "payment_status": "CONFIRMED",
  "print_job_id": 5,
  "print_job_status": "COMPLETED"
}
```

This endpoint simulates successful payment confirmation. After confirmation, the system creates a print job and updates its status.

---

### 5. Reject Payment for a Print Request

Endpoint:

```http
POST /api/requests/<request_id>/payment/reject/
```

Example request:

```bash
curl.exe -H "Authorization: Token YOUR_TOKEN_HERE" ^
  -X POST http://127.0.0.1:8000/api/requests/10/payment/reject/
```

Example response:

```json
{
  "message": "Payment rejected.",
  "payment_status": "REJECTED",
  "print_request_status": "PAYMENT_FAILED"
}
```

This endpoint simulates rejected payment. In this case, the print job is not created.

---

## Tested Workflow

The following workflow was successfully tested:

1. User obtains an API token.
2. User accesses their own print requests using token authentication.
3. User uploads a document and creates a print request.
4. The system validates the uploaded file.
5. The system stores print settings and calculates the price.
6. The user confirms payment through the payment simulation endpoint.
7. The system creates a print job after successful payment.
8. The print job status is updated successfully.

This confirms that the main Chapify API workflow is functional:

```text
Login → Token Authentication → File Upload → Print Settings → Price Calculation → Payment Confirmation → Print Job Creation
```

## Security Note

Real authentication tokens must never be committed to GitHub or included in public documentation.
All examples in this documentation use the placeholder value:

```text
YOUR_TOKEN_HERE
```
