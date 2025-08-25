# RAG-Anything Native Python API - OpenAPI 3.0 Specification

```yaml
openapi: 3.0.0
info:
  title: RAG-Anything Native Python API
  version: 1.0.0
  description: |
    Native Python REST API for RAG-Anything multimodal document processing and querying.
    
    This API provides direct integration with RAG-Anything Python modules, eliminating
    subprocess overhead while maintaining full feature compatibility.
    
    ## Features
    - Document processing (PDF, Office, images, text)
    - Multimodal content querying
    - VLM-enhanced visual analysis
    - Batch processing capabilities
    - Knowledge base management
    - Real-time streaming responses
    
    ## Authentication
    This API supports two authentication methods:
    
    ### API Key Authentication (Recommended)
    - Add header: `X-API-Key: your_api_key`
    - Best for service-to-service integration
    - Keys can be scoped with specific permissions
    
    ### JWT Token Authentication
    - Add header: `Authorization: Bearer your_jwt_token`
    - Best for web applications with user sessions
    - Tokens expire and can be refreshed
    
    ## Rate Limiting
    - Rate limits are applied per API key/user
    - Default: 100 requests per minute for authenticated users
    - Rate limit headers included in responses
    - 429 status code returned when limit exceeded
    
    ## Security Features
    - HTTPS required for all requests in production
    - Input validation and sanitization
    - File upload security scanning
    - Audit logging for sensitive operations
    - CORS configuration for web clients
    
  contact:
    name: RAG-Anything API Support
    url: https://github.com/HKUDS/RAG-Anything
    email: support@raganything.com
  license:
    name: MIT
    url: https://opensource.org/licenses/MIT

servers:
  - url: https://api.raganything.com/v1
    description: Production server
  - url: https://staging-api.raganything.com/v1
    description: Staging server
  - url: http://localhost:8000/api/v1
    description: Development server

security:
  - ApiKeyAuth: []
  - JWTAuth: []

paths:
  # Authentication Endpoints
  /auth/token:
    post:
      tags:
        - Authentication
      summary: Obtain JWT access token
      description: |
        Exchange user credentials for a JWT access token and refresh token.
        The access token expires after 1 hour, refresh token after 7 days.
      operationId: getAccessToken
      security: []  # No authentication required for this endpoint
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - username
                - password
              properties:
                username:
                  type: string
                  description: User username or email
                  example: "user@example.com"
                password:
                  type: string
                  format: password
                  description: User password
                  example: "secure_password"
      responses:
        200:
          description: Authentication successful
          content:
            application/json:
              schema:
                type: object
                properties:
                  access_token:
                    type: string
                    description: JWT access token (expires in 1 hour)
                    example: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                  refresh_token:
                    type: string
                    description: JWT refresh token (expires in 7 days)
                    example: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                  token_type:
                    type: string
                    example: "bearer"
                  expires_in:
                    type: integer
                    description: Access token expiration time in seconds
                    example: 3600
                  user:
                    type: object
                    properties:
                      user_id:
                        type: string
                        example: "user_123"
                      username:
                        type: string
                        example: "user@example.com"
                      permissions:
                        type: array
                        items:
                          type: string
                        example: ["documents:read", "documents:write", "queries:execute"]
        401:
          $ref: '#/components/responses/Unauthorized'
        429:
          $ref: '#/components/responses/RateLimitExceeded'

  /auth/refresh:
    post:
      tags:
        - Authentication
      summary: Refresh JWT access token
      description: |
        Exchange a valid refresh token for a new access token.
        Refresh tokens can only be used once and a new refresh token is issued.
      operationId: refreshToken
      security: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - refresh_token
              properties:
                refresh_token:
                  type: string
                  description: Valid refresh token
                  example: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
      responses:
        200:
          description: Token refreshed successfully
          content:
            application/json:
              schema:
                type: object
                properties:
                  access_token:
                    type: string
                    example: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                  refresh_token:
                    type: string
                    example: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                  token_type:
                    type: string
                    example: "bearer"
                  expires_in:
                    type: integer
                    example: 3600
        401:
          $ref: '#/components/responses/Unauthorized'

  /auth/api-keys:
    post:
      tags:
        - Authentication
      summary: Generate new API key
      description: |
        Generate a new API key with specified permissions.
        Requires admin privileges.
      operationId: generateApiKey
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - name
                - permissions
              properties:
                name:
                  type: string
                  description: Descriptive name for the API key
                  example: "Production Integration"
                permissions:
                  type: array
                  items:
                    type: string
                  description: List of permissions to grant
                  example: ["documents:read", "documents:write", "queries:execute"]
                expires_in:
                  type: integer
                  description: Optional expiration time in seconds (default: no expiration)
                  example: 2592000
      responses:
        201:
          description: API key created successfully
          content:
            application/json:
              schema:
                type: object
                properties:
                  api_key:
                    type: string
                    description: The generated API key (shown only once)
                    example: "ak_live_1234567890abcdef"
                  key_id:
                    type: string
                    description: Unique identifier for the API key
                    example: "key_abc123"
                  name:
                    type: string
                    example: "Production Integration"
                  permissions:
                    type: array
                    items:
                      type: string
                    example: ["documents:read", "documents:write"]
                  created_at:
                    type: string
                    format: date-time
                  expires_at:
                    type: string
                    format: date-time
                    nullable: true

  # Document Processing Endpoints
  /documents/process:
    post:
      tags:
        - Document Processing
      summary: Process single document
      description: |
        Upload and process a single document through the RAG pipeline.
        Supports multiple document formats and parser configurations.
      operationId: processDocument
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              type: object
              required:
                - file
              properties:
                file:
                  type: string
                  format: binary
                  description: Document file to process
                parser:
                  type: string
                  enum: [auto, mineru, docling]
                  default: auto
                  description: Parser to use for document processing
                parse_method:
                  type: string
                  enum: [auto, ocr, txt, hybrid]
                  default: auto
                  description: Parsing method selection
                working_dir:
                  type: string
                  default: "./storage"
                  description: Working directory for processing
                config:
                  type: object
                  description: Parser-specific configuration
                  properties:
                    lang:
                      type: string
                      default: "en"
                      description: Language for OCR processing
                    device:
                      type: string
                      enum: [cpu, cuda]
                      default: "cpu"
                      description: Processing device
                    start_page:
                      type: integer
                      minimum: 1
                      description: Starting page for processing
                    end_page:
                      type: integer
                      minimum: 1
                      description: Ending page for processing
                    enable_image_processing:
                      type: boolean
                      default: true
                      description: Enable image extraction
                    chunk_size:
                      type: integer
                      default: 1000
                      minimum: 100
                      maximum: 4000
                      description: Text chunk size
                    chunk_overlap:
                      type: integer
                      default: 200
                      minimum: 0
                      maximum: 1000
                      description: Chunk overlap size
      responses:
        200:
          description: Document processed successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
              description: Request limit per time window
            X-RateLimit-Remaining:
              schema:
                type: integer
              description: Remaining requests in current window
            X-RateLimit-Reset:
              schema:
                type: integer
              description: Time when the rate limit resets (Unix timestamp)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DocumentProcessResult'
              example:
                document_id: "doc_123456"
                status: "completed"
                processing_time: 12.45
                content_stats:
                  total_pages: 10
                  text_blocks: 45
                  images: 3
                  tables: 2
                  equations: 1
                metadata:
                  filename: "research_paper.pdf"
                  file_size: 2048576
                  parser_used: "mineru"
        400:
          $ref: '#/components/responses/BadRequest'
        401:
          $ref: '#/components/responses/Unauthorized'
        403:
          $ref: '#/components/responses/Forbidden'
        413:
          $ref: '#/components/responses/PayloadTooLarge'
        429:
          $ref: '#/components/responses/RateLimitExceeded'
        500:
          $ref: '#/components/responses/InternalServerError'

  /documents/batch:
    post:
      tags:
        - Document Processing
      summary: Process multiple documents
      description: |
        Process multiple documents concurrently in a batch job.
        Returns a job ID for tracking progress.
      operationId: batchProcessDocuments
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - file_ids
              properties:
                file_ids:
                  type: array
                  items:
                    type: string
                  description: List of uploaded file IDs to process
                  example: ["file_001", "file_002", "file_003"]
                config:
                  $ref: '#/components/schemas/ProcessingConfig'
                max_concurrent:
                  type: integer
                  default: 4
                  minimum: 1
                  maximum: 10
                  description: Maximum concurrent processing jobs
                kb_id:
                  type: string
                  default: "default"
                  description: Target knowledge base ID
      responses:
        202:
          description: Batch job created successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
            X-RateLimit-Reset:
              schema:
                type: integer
          content:
            application/json:
              schema:
                type: object
                properties:
                  job_id:
                    type: string
                    description: Batch job identifier
                    example: "batch_789012"
                  status:
                    type: string
                    enum: [queued, processing]
                    example: "queued"
                  estimated_completion:
                    type: string
                    format: date-time
                    description: Estimated completion time
                  files_count:
                    type: integer
                    description: Number of files in batch
                    example: 3
        400:
          $ref: '#/components/responses/BadRequest'
        401:
          $ref: '#/components/responses/Unauthorized'
        403:
          $ref: '#/components/responses/Forbidden'

  /documents/{job_id}/status:
    get:
      tags:
        - Document Processing
      summary: Get processing job status
      description: Retrieve the status and progress of a document processing job
      operationId: getJobStatus
      parameters:
        - name: job_id
          in: path
          required: true
          schema:
            type: string
          description: Job identifier
          example: "batch_789012"
      responses:
        200:
          description: Job status retrieved successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/JobStatus'
              example:
                job_id: "batch_789012"
                status: "processing"
                progress: 66.7
                completed_files: 2
                total_files: 3
                results:
                  - file_id: "file_001"
                    document_id: "doc_001"
                    status: "completed"
                  - file_id: "file_002"
                    document_id: "doc_002"
                    status: "completed"
                  - file_id: "file_003"
                    status: "processing"
                created_at: "2024-01-15T10:30:00Z"
                updated_at: "2024-01-15T10:32:30Z"
        404:
          $ref: '#/components/responses/NotFound'

  # Query Processing Endpoints
  /query/text:
    post:
      tags:
        - Querying
      summary: Execute text query
      description: |
        Perform a text-based query against the knowledge base.
        Supports different query modes and response streaming.
      operationId: textQuery
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TextQueryRequest'
            example:
              query: "What are the key findings about machine learning performance?"
              mode: "hybrid"
              kb_id: "default"
              top_k: 10
              stream: false
      responses:
        200:
          description: Query executed successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
            X-Processing-Time:
              schema:
                type: number
              description: Query processing time in seconds
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/QueryResult'
              example:
                query: "What are the key findings about machine learning performance?"
                mode: "hybrid"
                results:
                  - content: "Machine learning models showed 95% accuracy..."
                    score: 0.892
                    source:
                      document_id: "doc_123"
                      page: 5
                      bbox: [100, 200, 300, 250]
                    metadata:
                      content_type: "text"
                  - content: "Performance metrics indicate significant improvements..."
                    score: 0.854
                    source:
                      document_id: "doc_456"
                      page: 12
                processing_time: 1.23
                total_results: 15
        400:
          $ref: '#/components/responses/BadRequest'
        401:
          $ref: '#/components/responses/Unauthorized'
        403:
          $ref: '#/components/responses/Forbidden'

  /query/text/stream:
    post:
      tags:
        - Querying
      summary: Execute streaming text query
      description: |
        Execute a text query with streaming response using Server-Sent Events.
        Results are streamed in real-time as they become available.
      operationId: streamTextQuery
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TextQueryRequest'
      responses:
        200:
          description: Streaming query response
          headers:
            Content-Type:
              schema:
                type: string
                example: "text/event-stream"
            Cache-Control:
              schema:
                type: string
                example: "no-cache"
            Connection:
              schema:
                type: string
                example: "keep-alive"
          content:
            text/event-stream:
              schema:
                type: string
              example: |
                event: chunk
                data: {"chunk_id": 1, "results": [...], "is_final": false}
                
                event: chunk
                data: {"chunk_id": 2, "results": [...], "is_final": false}
                
                event: complete
                data: {"total_results": 15, "processing_time": 2.34}

  /query/multimodal:
    post:
      tags:
        - Querying
      summary: Execute multimodal query
      description: |
        Perform a query with multimodal content (images, tables, equations).
        The query engine will analyze both text and provided multimodal content.
      operationId: multimodalQuery
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/MultimodalQueryRequest'
            example:
              query: "Compare this table with similar data in documents"
              multimodal_content:
                - type: "table"
                  table_data:
                    headers: ["Model", "Accuracy", "F1-Score"]
                    rows:
                      - ["BERT", "92.3%", "0.89"]
                      - ["GPT-4", "95.1%", "0.92"]
                  table_caption: "Model Performance Comparison"
              mode: "hybrid"
              kb_id: "default"
      responses:
        200:
          description: Multimodal query executed successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
            X-Processing-Time:
              schema:
                type: number
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/QueryResult'
        400:
          $ref: '#/components/responses/BadRequest'
        403:
          $ref: '#/components/responses/Forbidden'

  /query/vlm-enhanced:
    post:
      tags:
        - Querying
      summary: Execute VLM-enhanced query
      description: |
        Perform a query with Vision Language Model enhancement.
        Images in retrieved context are automatically analyzed by VLM.
      operationId: vlmEnhancedQuery
      requestBody:
        required: true
        content:
          application/json:
            schema:
              allOf:
                - $ref: '#/components/schemas/TextQueryRequest'
                - type: object
                  properties:
                    vlm_enhanced:
                      type: boolean
                      default: true
                      description: Enable VLM enhancement
                    vlm_model:
                      type: string
                      enum: [gpt-4-vision, claude-3-vision, gemini-pro-vision]
                      default: "gpt-4-vision"
                      description: VLM model to use
            example:
              query: "Analyze the charts and graphs in the financial reports"
              mode: "hybrid"
              vlm_enhanced: true
              vlm_model: "gpt-4-vision"
      responses:
        200:
          description: VLM-enhanced query executed successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
            X-Processing-Time:
              schema:
                type: number
            X-VLM-Calls:
              schema:
                type: integer
              description: Number of VLM API calls made
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/QueryResult'
                  - type: object
                    properties:
                      vlm_analysis:
                        type: array
                        items:
                          type: object
                          properties:
                            image_id:
                              type: string
                            analysis:
                              type: string
                            confidence:
                              type: number
                              minimum: 0
                              maximum: 1
        400:
          $ref: '#/components/responses/BadRequest'
        403:
          $ref: '#/components/responses/Forbidden'
        503:
          description: VLM service unavailable
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'

  # Content Management Endpoints  
  /content/insert:
    post:
      tags:
        - Content Management
      summary: Insert content directly
      description: |
        Insert pre-parsed structured content directly into the knowledge base.
        Useful for integrating external parsing systems or custom content.
      operationId: insertContent
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - content_list
              properties:
                content_list:
                  type: array
                  items:
                    $ref: '#/components/schemas/ContentItem'
                  description: List of content items to insert
                file_path:
                  type: string
                  description: Original file path (for reference)
                  example: "/uploads/document.pdf"
                doc_id:
                  type: string
                  description: Custom document ID (auto-generated if not provided)
                  example: "custom_doc_001"
                kb_id:
                  type: string
                  default: "default"
                  description: Target knowledge base
            example:
              content_list:
                - content_type: "text"
                  content_data: "This is the introduction section..."
                  metadata:
                    page_number: 1
                    section: "Introduction"
                - content_type: "table"
                  content_data:
                    headers: ["Year", "Revenue", "Growth"]
                    rows: [["2023", "$100M", "15%"]]
                  metadata:
                    page_number: 5
                    table_caption: "Financial Performance"
              file_path: "/uploads/annual_report.pdf"
              doc_id: "annual_report_2023"
      responses:
        201:
          description: Content inserted successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
          content:
            application/json:
              schema:
                type: object
                properties:
                  document_id:
                    type: string
                    description: Document identifier
                    example: "doc_789012"
                  inserted_items:
                    type: integer
                    description: Number of content items inserted
                    example: 25
                  processing_time:
                    type: number
                    description: Processing time in seconds
                    example: 2.15
                  status:
                    type: string
                    enum: [success]
                    example: "success"
        400:
          $ref: '#/components/responses/BadRequest'
        403:
          $ref: '#/components/responses/Forbidden'

  # Knowledge Base Management
  /kb/{kb_id}/info:
    get:
      tags:
        - Knowledge Base
      summary: Get knowledge base information
      description: Retrieve metadata and statistics for a knowledge base
      operationId: getKnowledgeBaseInfo
      parameters:
        - $ref: '#/components/parameters/KnowledgeBaseId'
      responses:
        200:
          description: Knowledge base information retrieved
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/KnowledgeBaseInfo'
              example:
                kb_id: "default"
                name: "Default Knowledge Base"
                created_at: "2024-01-01T00:00:00Z"
                updated_at: "2024-01-15T10:30:00Z"
                document_count: 150
                total_content_items: 5420
                storage_size_mb: 256.5
                last_indexed: "2024-01-15T09:45:00Z"
        404:
          $ref: '#/components/responses/NotFound'

  /kb/{kb_id}/documents:
    get:
      tags:
        - Knowledge Base
      summary: List documents in knowledge base
      description: Retrieve a paginated list of documents in the knowledge base
      operationId: listDocuments
      parameters:
        - $ref: '#/components/parameters/KnowledgeBaseId'
        - name: page
          in: query
          schema:
            type: integer
            minimum: 1
            default: 1
          description: Page number
        - name: limit
          in: query
          schema:
            type: integer
            minimum: 1
            maximum: 100
            default: 20
          description: Number of items per page
        - name: search
          in: query
          schema:
            type: string
          description: Search query for document names
        - name: sort
          in: query
          schema:
            type: string
            enum: [created_at, updated_at, name, size]
            default: created_at
          description: Sort field
        - name: order
          in: query
          schema:
            type: string
            enum: [asc, desc]
            default: desc
          description: Sort order
      responses:
        200:
          description: Documents retrieved successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
          content:
            application/json:
              schema:
                type: object
                properties:
                  documents:
                    type: array
                    items:
                      $ref: '#/components/schemas/DocumentInfo'
                  pagination:
                    $ref: '#/components/schemas/Pagination'
                example:
                  documents:
                    - document_id: "doc_001"
                      filename: "research_paper.pdf"
                      created_at: "2024-01-15T10:30:00Z"
                      content_count: 45
                      file_size: 2048576
                    - document_id: "doc_002"
                      filename: "presentation.pptx"
                      created_at: "2024-01-14T15:20:00Z"
                      content_count: 28
                      file_size: 5242880
                  pagination:
                    page: 1
                    limit: 20
                    total: 150
                    pages: 8
        404:
          $ref: '#/components/responses/NotFound'

  /kb/{kb_id}/documents/{doc_id}:
    delete:
      tags:
        - Knowledge Base
      summary: Delete document from knowledge base
      description: Remove a document and all its content from the knowledge base
      operationId: deleteDocument
      parameters:
        - $ref: '#/components/parameters/KnowledgeBaseId'
        - name: doc_id
          in: path
          required: true
          schema:
            type: string
          description: Document identifier
          example: "doc_123456"
      responses:
        204:
          description: Document deleted successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
        404:
          $ref: '#/components/responses/NotFound'
        409:
          description: Document cannot be deleted (e.g., referenced by other content)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'

  # File Management Endpoints
  /files/upload:
    post:
      tags:
        - File Management
      summary: Upload file
      description: |
        Upload a file for processing. Returns a file ID that can be used
        in other endpoints. Files are automatically cleaned up after processing.
      operationId: uploadFile
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              type: object
              required:
                - file
              properties:
                file:
                  type: string
                  format: binary
                  description: File to upload
                expires_in:
                  type: integer
                  default: 3600
                  minimum: 300
                  maximum: 86400
                  description: File expiration time in seconds
      responses:
        201:
          description: File uploaded successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
          content:
            application/json:
              schema:
                type: object
                properties:
                  file_id:
                    type: string
                    description: Unique file identifier
                    example: "file_abc123"
                  filename:
                    type: string
                    description: Original filename
                    example: "document.pdf"
                  file_size:
                    type: integer
                    description: File size in bytes
                    example: 2048576
                  content_type:
                    type: string
                    description: MIME type
                    example: "application/pdf"
                  expires_at:
                    type: string
                    format: date-time
                    description: File expiration timestamp
                    example: "2024-01-15T11:30:00Z"
        400:
          $ref: '#/components/responses/BadRequest'
        413:
          $ref: '#/components/responses/PayloadTooLarge'

  /files/upload/chunk:
    post:
      tags:
        - File Management
      summary: Upload file chunk
      description: |
        Upload a file in chunks for large file support with resume capability.
        Use this for files larger than 100MB.
      operationId: uploadFileChunk
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              type: object
              required:
                - upload_id
                - chunk_index
                - total_chunks
                - chunk_data
              properties:
                upload_id:
                  type: string
                  description: Upload session identifier
                  example: "upload_xyz789"
                chunk_index:
                  type: integer
                  minimum: 0
                  description: Zero-based chunk index
                  example: 0
                total_chunks:
                  type: integer
                  minimum: 1
                  description: Total number of chunks
                  example: 10
                chunk_data:
                  type: string
                  format: binary
                  description: Chunk data
                filename:
                  type: string
                  description: Original filename (required for first chunk)
                  example: "large_document.pdf"
      responses:
        200:
          description: Chunk uploaded successfully (not last chunk)
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
          content:
            application/json:
              schema:
                type: object
                properties:
                  upload_id:
                    type: string
                    example: "upload_xyz789"
                  chunk_index:
                    type: integer
                    example: 0
                  status:
                    type: string
                    enum: [chunk_received, uploading]
                    example: "chunk_received"
        201:
          description: Final chunk uploaded, file complete
          content:
            application/json:
              schema:
                type: object
                properties:
                  file_id:
                    type: string
                    example: "file_def456"
                  upload_id:
                    type: string
                    example: "upload_xyz789"
                  status:
                    type: string
                    enum: [completed]
                    example: "completed"
                  file_size:
                    type: integer
                    example: 104857600
        400:
          $ref: '#/components/responses/BadRequest'

  /files/{file_id}:
    get:
      tags:
        - File Management
      summary: Get file metadata
      description: Retrieve metadata for an uploaded file
      operationId: getFileMetadata
      parameters:
        - name: file_id
          in: path
          required: true
          schema:
            type: string
          description: File identifier
          example: "file_abc123"
      responses:
        200:
          description: File metadata retrieved
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/FileMetadata'
              example:
                file_id: "file_abc123"
                filename: "document.pdf"
                file_size: 2048576
                content_type: "application/pdf"
                created_at: "2024-01-15T10:30:00Z"
                expires_at: "2024-01-15T11:30:00Z"
                status: "uploaded"
        404:
          $ref: '#/components/responses/NotFound'

    delete:
      tags:
        - File Management
      summary: Delete uploaded file
      description: Remove an uploaded file from storage
      operationId: deleteFile
      parameters:
        - name: file_id
          in: path
          required: true
          schema:
            type: string
          description: File identifier
          example: "file_abc123"
      responses:
        204:
          description: File deleted successfully
          headers:
            X-RateLimit-Limit:
              schema:
                type: integer
            X-RateLimit-Remaining:
              schema:
                type: integer
        404:
          $ref: '#/components/responses/NotFound'

  # Configuration and Status Endpoints
  /config/parsers:
    get:
      tags:
        - Configuration
      summary: List available parsers
      description: Get information about available document parsers and their capabilities
      operationId: listParsers
      responses:
        200:
          description: Available parsers information
          content:
            application/json:
              schema:
                type: object
                properties:
                  parsers:
                    type: array
                    items:
                      $ref: '#/components/schemas/ParserInfo'
                example:
                  parsers:
                    - name: "mineru"
                      display_name: "MinerU Parser"
                      supported_formats: ["pdf", "docx", "pptx", "jpg", "png"]
                      capabilities: ["ocr", "table_extraction", "image_extraction"]
                      version: "0.8.2"
                      available: true
                    - name: "docling"
                      display_name: "Docling Parser"
                      supported_formats: ["pdf", "html", "docx"]
                      capabilities: ["layout_analysis", "structured_extraction"]
                      version: "1.2.0"
                      available: true

  /config/formats:
    get:
      tags:
        - Configuration
      summary: List supported file formats
      description: Get information about supported file formats and their processors
      operationId: listSupportedFormats
      responses:
        200:
          description: Supported file formats
          content:
            application/json:
              schema:
                type: object
                properties:
                  formats:
                    type: array
                    items:
                      type: object
                      properties:
                        extension:
                          type: string
                          example: "pdf"
                        mime_type:
                          type: string
                          example: "application/pdf"
                        supported_parsers:
                          type: array
                          items:
                            type: string
                          example: ["mineru", "docling"]
                        max_file_size_mb:
                          type: integer
                          example: 100

  /health:
    get:
      tags:
        - Health & Monitoring
      summary: Basic health check
      description: Simple health check endpoint for load balancers
      operationId: healthCheck
      security: []
      responses:
        200:
          description: Service is healthy
          headers:
            X-Content-Type-Options:
              schema:
                type: string
              example: "nosniff"
            X-Frame-Options:
              schema:
                type: string
              example: "DENY"
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    enum: [healthy]
                    example: "healthy"
                  timestamp:
                    type: string
                    format: date-time
                    example: "2024-01-15T10:30:00Z"
                  version:
                    type: string
                    example: "1.0.0"

  /status:
    get:
      tags:
        - Health & Monitoring
      summary: Detailed system status
      description: Comprehensive system status including component health
      operationId: detailedStatus
      responses:
        200:
          description: System status retrieved
          headers:
            X-Content-Type-Options:
              schema:
                type: string
              example: "nosniff"
            X-Frame-Options:
              schema:
                type: string
              example: "DENY"
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SystemStatus'
              example:
                status: "healthy"
                components:
                  lightrag: "healthy"
                  redis: "healthy"
                  disk_space: "ok"
                  memory_usage: "ok"
                metrics:
                  uptime_seconds: 86400
                  total_requests: 15420
                  active_connections: 12
                  memory_usage_mb: 2048
                  disk_usage_percent: 45.2
                timestamp: "2024-01-15T10:30:00Z"

  /metrics:
    get:
      tags:
        - Health & Monitoring
      summary: Prometheus metrics
      description: Export metrics in Prometheus format
      operationId: getMetrics
      responses:
        200:
          description: Metrics in Prometheus format
          headers:
            Content-Type:
              schema:
                type: string
              example: "text/plain; version=0.0.4; charset=utf-8"
            X-Content-Type-Options:
              schema:
                type: string
              example: "nosniff"
          content:
            text/plain:
              schema:
                type: string
              example: |
                # HELP raganything_requests_total Total HTTP requests
                # TYPE raganything_requests_total counter
                raganything_requests_total{method="POST",endpoint="/api/v1/query/text"} 1543
                
                # HELP raganything_request_duration_seconds Request duration
                # TYPE raganything_request_duration_seconds histogram
                raganything_request_duration_seconds_bucket{le="0.1"} 120
                raganything_request_duration_seconds_bucket{le="0.5"} 450
                raganything_request_duration_seconds_bucket{le="1.0"} 1200

components:
  securitySchemes:
    ApiKeyAuth:
      type: apiKey
      in: header
      name: X-API-Key
      description: |
        API key for authentication. Include the key in the X-API-Key header:
        
        ```
        X-API-Key: ak_live_1234567890abcdef
        ```
        
        API keys can be generated via the /auth/api-keys endpoint.
        Each key has specific permissions and optional expiration.
    JWTAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
      description: |
        JWT token authentication. Include the token in the Authorization header:
        
        ```
        Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
        ```
        
        Tokens can be obtained via the /auth/token endpoint and expire after 1 hour.
        Use the refresh token to obtain new access tokens.

  parameters:
    KnowledgeBaseId:
      name: kb_id
      in: path
      required: true
      schema:
        type: string
        default: "default"
      description: Knowledge base identifier
      example: "default"

  schemas:
    # Core Models
    ProcessingConfig:
      type: object
      properties:
        parser:
          type: string
          enum: [auto, mineru, docling]
          default: auto
        parse_method:
          type: string
          enum: [auto, ocr, txt, hybrid]
          default: auto
        config:
          type: object
          properties:
            lang:
              type: string
              default: "en"
            device:
              type: string
              enum: [cpu, cuda]
              default: "cpu"
            start_page:
              type: integer
              minimum: 1
            end_page:
              type: integer
              minimum: 1
            enable_image_processing:
              type: boolean
              default: true
            chunk_size:
              type: integer
              default: 1000
              minimum: 100
              maximum: 4000
            chunk_overlap:
              type: integer
              default: 200
              minimum: 0
              maximum: 1000

    ContentItem:
      type: object
      required:
        - content_type
        - content_data
      properties:
        content_type:
          type: string
          enum: [text, image, table, equation]
          description: Type of content
        content_data:
          oneOf:
            - type: string
            - type: object
          description: Content data (format depends on content_type)
        metadata:
          type: object
          properties:
            page_number:
              type: integer
              minimum: 1
            bbox:
              type: array
              items:
                type: number
              minItems: 4
              maxItems: 4
              description: Bounding box coordinates [x1, y1, x2, y2]
            section:
              type: string
              description: Document section
            confidence:
              type: number
              minimum: 0
              maximum: 1
              description: Extraction confidence score
          additionalProperties: true

    TextQueryRequest:
      type: object
      required:
        - query
      properties:
        query:
          type: string
          minLength: 1
          maxLength: 2000
          description: Query text
          example: "What are the main conclusions of the research?"
        mode:
          type: string
          enum: [hybrid, local, global, naive]
          default: hybrid
          description: Query processing mode
        kb_id:
          type: string
          default: "default"
          description: Knowledge base to query
        top_k:
          type: integer
          minimum: 1
          maximum: 100
          default: 10
          description: Maximum number of results
        stream:
          type: boolean
          default: false
          description: Enable streaming response
        filters:
          type: object
          description: Additional query filters
          properties:
            document_ids:
              type: array
              items:
                type: string
              description: Limit search to specific documents
            date_range:
              type: object
              properties:
                start:
                  type: string
                  format: date
                end:
                  type: string
                  format: date
            content_types:
              type: array
              items:
                type: string
                enum: [text, image, table, equation]

    MultimodalQueryRequest:
      allOf:
        - $ref: '#/components/schemas/TextQueryRequest'
        - type: object
          properties:
            multimodal_content:
              type: array
              items:
                $ref: '#/components/schemas/ContentItem'
              description: Multimodal content to include in query

    QueryResult:
      type: object
      properties:
        query:
          type: string
          description: Original query text
        mode:
          type: string
          description: Query mode used
        results:
          type: array
          items:
            $ref: '#/components/schemas/QueryResultItem'
        processing_time:
          type: number
          description: Query processing time in seconds
        total_results:
          type: integer
          description: Total number of results found
        metadata:
          type: object
          description: Additional query metadata
          properties:
            kb_id:
              type: string
            model_used:
              type: string
            cache_hit:
              type: boolean

    QueryResultItem:
      type: object
      properties:
        content:
          type: string
          description: Retrieved content
        score:
          type: number
          minimum: 0
          maximum: 1
          description: Relevance score
        source:
          type: object
          properties:
            document_id:
              type: string
            page:
              type: integer
            bbox:
              type: array
              items:
                type: number
              minItems: 4
              maxItems: 4
            chunk_id:
              type: string
        metadata:
          type: object
          properties:
            content_type:
              type: string
              enum: [text, image, table, equation]
            section:
              type: string
            filename:
              type: string
          additionalProperties: true

    DocumentProcessResult:
      type: object
      properties:
        document_id:
          type: string
          description: Generated document identifier
        status:
          type: string
          enum: [completed, failed]
        processing_time:
          type: number
          description: Processing time in seconds
        content_stats:
          type: object
          properties:
            total_pages:
              type: integer
            text_blocks:
              type: integer
            images:
              type: integer
            tables:
              type: integer
            equations:
              type: integer
        metadata:
          type: object
          properties:
            filename:
              type: string
            file_size:
              type: integer
            parser_used:
              type: string
            extraction_config:
              type: object
        errors:
          type: array
          items:
            type: object
            properties:
              page:
                type: integer
              error_type:
                type: string
              message:
                type: string

    JobStatus:
      type: object
      properties:
        job_id:
          type: string
          description: Job identifier
        status:
          type: string
          enum: [queued, processing, completed, failed, cancelled]
        progress:
          type: number
          minimum: 0
          maximum: 100
          description: Completion percentage
        completed_files:
          type: integer
          description: Number of completed files
        total_files:
          type: integer
          description: Total number of files in job
        results:
          type: array
          items:
            type: object
            properties:
              file_id:
                type: string
              document_id:
                type: string
              status:
                type: string
                enum: [queued, processing, completed, failed]
              error:
                type: string
                description: Error message if status is failed
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time
        estimated_completion:
          type: string
          format: date-time

    KnowledgeBaseInfo:
      type: object
      properties:
        kb_id:
          type: string
          description: Knowledge base identifier
        name:
          type: string
          description: Human-readable name
        description:
          type: string
          description: Knowledge base description
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time
        document_count:
          type: integer
          description: Number of documents
        total_content_items:
          type: integer
          description: Total content items across all documents
        storage_size_mb:
          type: number
          description: Storage size in megabytes
        last_indexed:
          type: string
          format: date-time
          description: Last indexing timestamp
        statistics:
          type: object
          properties:
            content_types:
              type: object
              properties:
                text:
                  type: integer
                images:
                  type: integer
                tables:
                  type: integer
                equations:
                  type: integer
            languages:
              type: object
              additionalProperties:
                type: integer
            avg_query_response_time:
              type: number

    DocumentInfo:
      type: object
      properties:
        document_id:
          type: string
        filename:
          type: string
        file_size:
          type: integer
        content_count:
          type: integer
          description: Number of content items
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time
        status:
          type: string
          enum: [processing, indexed, error]
        metadata:
          type: object
          properties:
            parser_used:
              type: string
            processing_time:
              type: number
            pages:
              type: integer
          additionalProperties: true

    FileMetadata:
      type: object
      properties:
        file_id:
          type: string
        filename:
          type: string
        file_size:
          type: integer
        content_type:
          type: string
        created_at:
          type: string
          format: date-time
        expires_at:
          type: string
          format: date-time
        status:
          type: string
          enum: [uploading, uploaded, processing, expired]
        metadata:
          type: object
          additionalProperties: true

    ParserInfo:
      type: object
      properties:
        name:
          type: string
          description: Parser internal name
        display_name:
          type: string
          description: Human-readable name
        version:
          type: string
          description: Parser version
        supported_formats:
          type: array
          items:
            type: string
          description: Supported file extensions
        capabilities:
          type: array
          items:
            type: string
          description: Parser capabilities
        available:
          type: boolean
          description: Whether parser is available
        configuration_options:
          type: object
          description: Available configuration parameters
          additionalProperties: true

    SystemStatus:
      type: object
      properties:
        status:
          type: string
          enum: [healthy, degraded, unhealthy]
        components:
          type: object
          properties:
            lightrag:
              type: string
              enum: [healthy, unhealthy]
            redis:
              type: string
              enum: [healthy, unhealthy]
            disk_space:
              type: string
              enum: [ok, warning, critical]
            memory_usage:
              type: string
              enum: [ok, warning, critical]
        metrics:
          type: object
          properties:
            uptime_seconds:
              type: integer
            total_requests:
              type: integer
            active_connections:
              type: integer
            memory_usage_mb:
              type: number
            disk_usage_percent:
              type: number
            cache_hit_rate:
              type: number
        timestamp:
          type: string
          format: date-time

    Pagination:
      type: object
      properties:
        page:
          type: integer
          minimum: 1
          description: Current page number
        limit:
          type: integer
          minimum: 1
          description: Items per page
        total:
          type: integer
          description: Total number of items
        pages:
          type: integer
          description: Total number of pages
        has_next:
          type: boolean
          description: Whether there is a next page
        has_prev:
          type: boolean
          description: Whether there is a previous page

    Error:
      type: object
      required:
        - error
        - message
      properties:
        error:
          type: string
          description: Error code
          example: "INVALID_REQUEST"
        message:
          type: string
          description: Human-readable error message
          example: "The request body is invalid"
        details:
          type: object
          description: Additional error details
          additionalProperties: true
        request_id:
          type: string
          description: Request identifier for tracing
          example: "req_abc123"
        timestamp:
          type: string
          format: date-time

  responses:
    BadRequest:
      description: Bad request - invalid parameters or request body
      headers:
        X-Content-Type-Options:
          schema:
            type: string
          example: "nosniff"
        X-Frame-Options:
          schema:
            type: string
          example: "DENY"
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: "INVALID_REQUEST"
            message: "Missing required field: query"
            details:
              field: "query"
              provided: null
              expected: "string"

    Unauthorized:
      description: Authentication required or invalid credentials
      headers:
        WWW-Authenticate:
          schema:
            type: string
          example: "Bearer realm=\"RAG-Anything API\", error=\"invalid_token\""
        X-Content-Type-Options:
          schema:
            type: string
          example: "nosniff"
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: "AUTHENTICATION_REQUIRED"
            message: "Valid API key or JWT token required"

    Forbidden:
      description: Access forbidden - insufficient permissions
      headers:
        X-Content-Type-Options:
          schema:
            type: string
          example: "nosniff"
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: "INSUFFICIENT_PERMISSIONS"
            message: "Required permission not granted for this operation"

    NotFound:
      description: Resource not found
      headers:
        X-Content-Type-Options:
          schema:
            type: string
          example: "nosniff"
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: "NOT_FOUND"
            message: "Document with ID 'doc_123' not found"

    PayloadTooLarge:
      description: Request payload too large
      headers:
        X-Content-Type-Options:
          schema:
            type: string
          example: "nosniff"
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: "PAYLOAD_TOO_LARGE"
            message: "File size exceeds maximum limit of 100MB"

    RateLimitExceeded:
      description: Rate limit exceeded
      headers:
        X-RateLimit-Limit:
          schema:
            type: integer
          description: Request limit per time window
        X-RateLimit-Remaining:
          schema:
            type: integer
          description: Remaining requests in current window
        X-RateLimit-Reset:
          schema:
            type: integer
          description: Time when the rate limit resets (Unix timestamp)
        Retry-After:
          schema:
            type: integer
          description: Seconds to wait before making another request
        X-Content-Type-Options:
          schema:
            type: string
          example: "nosniff"
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: "RATE_LIMIT_EXCEEDED"
            message: "API rate limit exceeded. Try again in 60 seconds"

    InternalServerError:
      description: Internal server error
      headers:
        X-Content-Type-Options:
          schema:
            type: string
          example: "nosniff"
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: "INTERNAL_SERVER_ERROR"
            message: "An unexpected error occurred"

# WebSocket Streaming Specification
# 
# WebSocket: wss://api.raganything.com/v1/ws/query/stream
# Purpose: Real-time query result streaming with bidirectional communication
# Authentication: Via query parameter ?token=<jwt_token> or ?api_key=<api_key>
# 
# Connection Example:
# ```javascript
# const ws = new WebSocket('wss://api.raganything.com/v1/ws/query/stream?api_key=ak_live_123');
# ```
# 
# Message Protocols:
#
# ## Client -> Server Messages
#
# ### Start Query
# ```json
# {
#   "type": "query_start",
#   "id": "query_001",
#   "data": {
#     "query": "What are the main findings in the research?",
#     "mode": "hybrid",
#     "kb_id": "default",
#     "top_k": 10,
#     "stream_chunks": true
#   }
# }
# ```
#
# ### Cancel Query
# ```json
# {
#   "type": "query_cancel",
#   "id": "query_001"
# }
# ```
#
# ## Server -> Client Messages
#
# ### Query Started
# ```json
# {
#   "type": "query_started",
#   "id": "query_001",
#   "data": {
#     "estimated_time": 2.5,
#     "query": "What are the main findings in the research?"
#   }
# }
# ```
#
# ### Result Chunk
# ```json
# {
#   "type": "result_chunk",
#   "id": "query_001",
#   "data": {
#     "chunk_id": 1,
#     "results": [
#       {
#         "content": "The research shows that...",
#         "score": 0.95,
#         "source": {
#           "document_id": "doc_123",
#           "page": 5
#         }
#       }
#     ],
#     "is_partial": true
#   }
# }
# ```
#
# ### Query Progress
# ```json
# {
#   "type": "query_progress",
#   "id": "query_001",
#   "data": {
#     "progress": 0.6,
#     "stage": "analyzing_results",
#     "processed_documents": 45
#   }
# }
# ```
#
# ### Query Complete
# ```json
# {
#   "type": "query_complete",
#   "id": "query_001",
#   "data": {
#     "total_results": 15,
#     "processing_time": 2.34,
#     "cache_saved": true
#   }
# }
# ```
#
# ### Error
# ```json
# {
#   "type": "error",
#   "id": "query_001",
#   "data": {
#     "error": "QUERY_TIMEOUT",
#     "message": "Query execution timed out after 30 seconds",
#     "details": {
#       "timeout_seconds": 30,
#       "partial_results_available": true
#     }
#   }
# }
# ```
#
# ## Connection Management
#
# ### Heartbeat (every 30 seconds)
# ```json
# {
#   "type": "ping"
# }
# ```
#
# Response:
# ```json
# {
#   "type": "pong",
#   "timestamp": "2024-01-15T10:30:00Z"
# }
# ```
#
# ## Rate Limiting
# - WebSocket connections are rate limited per API key
# - Maximum 5 concurrent queries per connection
# - Query rate limit: 60 queries per minute
# - Connection timeout: 10 minutes of inactivity
#
# ## Error Handling
# - Connection errors result in WebSocket close with appropriate code
# - Query errors are sent as error messages, connection remains open
# - Rate limit exceeded: Close code 1008 (Policy Violation)
# - Authentication failed: Close code 1008 (Policy Violation)
# - Internal error: Close code 1011 (Internal Error)
```

## API Usage Examples

### Python Client Example
```python
import requests
import asyncio
import aiohttp
import websockets
import json

class RAGAnythingClient:
    def __init__(self, base_url: str, api_key: str = None, jwt_token: str = None):
        self.base_url = base_url
        self.headers = {}
        
        if api_key:
            self.headers["X-API-Key"] = api_key
        elif jwt_token:
            self.headers["Authorization"] = f"Bearer {jwt_token}"
    
    async def authenticate(self, username: str, password: str) -> dict:
        """Authenticate and get JWT tokens"""
        url = f"{self.base_url}/auth/token"
        payload = {"username": username, "password": password}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    tokens = await response.json()
                    self.headers["Authorization"] = f"Bearer {tokens['access_token']}"
                    return tokens
                else:
                    raise Exception(f"Authentication failed: {response.status}")
    
    async def process_document(self, file_path: str, config: dict = None):
        """Process a single document"""
        url = f"{self.base_url}/documents/process"
        
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = config or {}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.headers, 
                                      data=data, files=files) as response:
                    return await response.json()
    
    async def text_query(self, query: str, mode: str = "hybrid"):
        """Execute a text query"""
        url = f"{self.base_url}/query/text"
        payload = {
            "query": query,
            "mode": mode,
            "top_k": 10
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, 
                                  json=payload) as response:
                return await response.json()
    
    async def multimodal_query(self, query: str, multimodal_content: list):
        """Execute multimodal query"""
        url = f"{self.base_url}/query/multimodal"
        payload = {
            "query": query,
            "multimodal_content": multimodal_content,
            "mode": "hybrid"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, 
                                  json=payload) as response:
                return await response.json()
    
    async def stream_query_websocket(self, query: str, on_chunk=None, on_complete=None):
        """Stream query results via WebSocket"""
        ws_url = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        
        # Add authentication to URL
        auth_param = ""
        if "X-API-Key" in self.headers:
            auth_param = f"?api_key={self.headers['X-API-Key']}"
        elif "Authorization" in self.headers:
            token = self.headers["Authorization"].replace("Bearer ", "")
            auth_param = f"?token={token}"
        
        uri = f"{ws_url}/ws/query/stream{auth_param}"
        
        async with websockets.connect(uri) as websocket:
            # Send query
            query_message = {
                "type": "query_start",
                "id": "query_001",
                "data": {
                    "query": query,
                    "mode": "hybrid",
                    "stream_chunks": True
                }
            }
            await websocket.send(json.dumps(query_message))
            
            # Listen for responses
            async for message in websocket:
                data = json.loads(message)
                
                if data["type"] == "result_chunk" and on_chunk:
                    on_chunk(data["data"])
                elif data["type"] == "query_complete" and on_complete:
                    on_complete(data["data"])
                    break
                elif data["type"] == "error":
                    raise Exception(f"Query error: {data['data']['message']}")

# Usage Examples
async def main():
    client = RAGAnythingClient("https://api.raganything.com/v1", api_key="your_api_key")
    
    # Alternative: Authenticate with username/password
    # tokens = await client.authenticate("user@example.com", "password")
    
    # Process document
    result = await client.process_document("document.pdf", {
        "parser": "mineru",
        "lang": "en",
        "chunk_size": 1000
    })
    print(f"Document ID: {result['document_id']}")
    
    # Simple text query
    response = await client.text_query("What are the main findings?")
    for item in response['results']:
        print(f"Score: {item['score']:.3f}, Content: {item['content'][:100]}...")
    
    # Multimodal query with table
    table_data = {
        "content_type": "table",
        "content_data": {
            "headers": ["Year", "Revenue", "Growth"],
            "rows": [["2023", "$100M", "15%"], ["2024", "$115M", "15%"]]
        },
        "metadata": {"table_caption": "Financial Performance"}
    }
    
    multimodal_response = await client.multimodal_query(
        "Analyze this financial data",
        [table_data]
    )
    print(f"Multimodal results: {len(multimodal_response['results'])}")
    
    # Streaming query
    def on_chunk(chunk_data):
        print(f"Received chunk {chunk_data['chunk_id']}: {len(chunk_data['results'])} results")
    
    def on_complete(complete_data):
        print(f"Query complete: {complete_data['total_results']} total results in {complete_data['processing_time']:.2f}s")
    
    await client.stream_query_websocket(
        "Streaming query example",
        on_chunk=on_chunk,
        on_complete=on_complete
    )

# Run the example
asyncio.run(main())
```

### JavaScript Client Example
```javascript
class RAGAnythingClient {
    constructor(baseUrl, apiKey = null, jwtToken = null) {
        this.baseUrl = baseUrl;
        this.headers = {
            'Content-Type': 'application/json'
        };
        
        if (apiKey) {
            this.headers['X-API-Key'] = apiKey;
        } else if (jwtToken) {
            this.headers['Authorization'] = `Bearer ${jwtToken}`;
        }
    }
    
    async authenticate(username, password) {
        const response = await fetch(`${this.baseUrl}/auth/token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        if (response.ok) {
            const tokens = await response.json();
            this.headers['Authorization'] = `Bearer ${tokens.access_token}`;
            return tokens;
        } else {
            throw new Error(`Authentication failed: ${response.status}`);
        }
    }
    
    async processDocument(file, config = {}) {
        const formData = new FormData();
        formData.append('file', file);
        
        // Add config parameters to form data
        Object.entries(config).forEach(([key, value]) => {
            formData.append(key, typeof value === 'object' ? JSON.stringify(value) : value);
        });
        
        const headers = { ...this.headers };
        delete headers['Content-Type']; // Let browser set it for FormData
        
        const response = await fetch(`${this.baseUrl}/documents/process`, {
            method: 'POST',
            headers: headers,
            body: formData
        });
        
        return await response.json();
    }
    
    async textQuery(query, mode = 'hybrid', options = {}) {
        const payload = {
            query,
            mode,
            top_k: 10,
            ...options
        };
        
        const response = await fetch(`${this.baseUrl}/query/text`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify(payload)
        });
        
        return await response.json();
    }
    
    async vlmEnhancedQuery(query, vlmModel = 'gpt-4-vision', options = {}) {
        const payload = {
            query,
            vlm_enhanced: true,
            vlm_model: vlmModel,
            mode: 'hybrid',
            ...options
        };
        
        const response = await fetch(`${this.baseUrl}/query/vlm-enhanced`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify(payload)
        });
        
        return await response.json();
    }
    
    // Server-Sent Events streaming
    streamQuery(query, onChunk, onComplete, onError) {
        const eventSource = new EventSource(
            `${this.baseUrl}/query/text/stream?` + new URLSearchParams({
                query,
                mode: 'hybrid',
                api_key: this.headers['X-API-Key'] || '',
                token: this.headers['Authorization']?.replace('Bearer ', '') || ''
            })
        );
        
        eventSource.addEventListener('chunk', (event) => {
            const data = JSON.parse(event.data);
            if (onChunk) onChunk(data);
        });
        
        eventSource.addEventListener('complete', (event) => {
            const data = JSON.parse(event.data);
            if (onComplete) onComplete(data);
            eventSource.close();
        });
        
        eventSource.addEventListener('error', (event) => {
            const errorData = JSON.parse(event.data);
            if (onError) onError(errorData);
            eventSource.close();
        });
        
        return eventSource;
    }
    
    // WebSocket streaming (alternative)
    streamQueryWebSocket(query, onChunk, onComplete, onError) {
        const wsUrl = this.baseUrl.replace('https:', 'wss:').replace('http:', 'ws:');
        
        // Add authentication to URL
        const authParam = this.headers['X-API-Key'] 
            ? `?api_key=${this.headers['X-API-Key']}`
            : `?token=${this.headers['Authorization']?.replace('Bearer ', '')}`;
        
        const ws = new WebSocket(`${wsUrl}/ws/query/stream${authParam}`);
        
        ws.onopen = () => {
            ws.send(JSON.stringify({
                type: 'query_start',
                id: 'query_' + Date.now(),
                data: {
                    query,
                    mode: 'hybrid',
                    stream_chunks: true
                }
            }));
        };
        
        ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            
            switch (message.type) {
                case 'result_chunk':
                    if (onChunk) onChunk(message.data);
                    break;
                case 'query_complete':
                    if (onComplete) onComplete(message.data);
                    ws.close();
                    break;
                case 'error':
                    if (onError) onError(message.data);
                    ws.close();
                    break;
            }
        };
        
        ws.onerror = (error) => {
            if (onError) onError({ error: 'WEBSOCKET_ERROR', message: 'WebSocket connection error' });
        };
        
        return ws;
    }
    
    async getKnowledgeBaseInfo(kbId = 'default') {
        const response = await fetch(`${this.baseUrl}/kb/${kbId}/info`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async listDocuments(kbId = 'default', page = 1, limit = 20) {
        const params = new URLSearchParams({ page: page.toString(), limit: limit.toString() });
        
        const response = await fetch(`${this.baseUrl}/kb/${kbId}/documents?${params}`, {
            headers: this.headers
        });
        return await response.json();
    }
}

// Usage Examples
async function examples() {
    const client = new RAGAnythingClient('https://api.raganything.com/v1', 'your_api_key');
    
    try {
        // Process document
        const fileInput = document.getElementById('fileInput');
        const file = fileInput.files[0];
        
        if (file) {
            const result = await client.processDocument(file, {
                parser: 'mineru',
                lang: 'en',
                chunk_size: 1000
            });
            console.log('Document processed:', result.document_id);
        }
        
        // Simple query
        const queryResult = await client.textQuery('What are the key findings?');
        console.log('Query results:', queryResult.results.length);
        
        // VLM enhanced query
        const vlmResult = await client.vlmEnhancedQuery(
            'Analyze the charts and diagrams',
            'gpt-4-vision'
        );
        console.log('VLM analysis:', vlmResult.vlm_analysis);
        
        // Streaming with Server-Sent Events
        const eventSource = client.streamQuery(
            'Streaming query example',
            (chunk) => console.log(`Chunk ${chunk.chunk_id}:`, chunk.results.length),
            (complete) => console.log('Complete:', complete.total_results),
            (error) => console.error('Error:', error)
        );
        
        // Alternative: WebSocket streaming
        const ws = client.streamQueryWebSocket(
            'WebSocket streaming example',
            (chunk) => console.log('WS Chunk:', chunk),
            (complete) => console.log('WS Complete:', complete),
            (error) => console.error('WS Error:', error)
        );
        
        // Knowledge base info
        const kbInfo = await client.getKnowledgeBaseInfo();
        console.log('KB Info:', kbInfo);
        
    } catch (error) {
        console.error('API Error:', error);
    }
}
```

### cURL Examples
```bash
# Authentication - Get JWT token
curl -X POST "https://api.raganything.com/v1/auth/token" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "user@example.com",
    "password": "your_password"
  }'

# Upload and process document
curl -X POST "https://api.raganything.com/v1/documents/process" \
  -H "X-API-Key: your_api_key" \
  -F "file=@document.pdf" \
  -F "parser=mineru" \
  -F "config={\"lang\":\"en\",\"device\":\"cpu\",\"chunk_size\":1000}"

# Text query
curl -X POST "https://api.raganything.com/v1/query/text" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the key findings?",
    "mode": "hybrid",
    "top_k": 5
  }'

# Multimodal query with table
curl -X POST "https://api.raganything.com/v1/query/multimodal" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Compare with this performance data",
    "multimodal_content": [{
      "content_type": "table",
      "content_data": {
        "headers": ["Model", "Accuracy"],
        "rows": [["BERT", "92.3%"], ["GPT-4", "95.1%"]]
      },
      "metadata": {
        "table_caption": "Model Performance"
      }
    }]
  }'

# VLM enhanced query
curl -X POST "https://api.raganything.com/v1/query/vlm-enhanced" \
  -H "Authorization: Bearer your_jwt_token" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze the charts and graphs in the documents",
    "vlm_enhanced": true,
    "vlm_model": "gpt-4-vision",
    "mode": "hybrid"
  }'

# Batch processing
curl -X POST "https://api.raganything.com/v1/documents/batch" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "file_ids": ["file_001", "file_002", "file_003"],
    "config": {
      "parser": "mineru",
      "lang": "en"
    },
    "max_concurrent": 3
  }'

# Check batch status
curl -X GET "https://api.raganything.com/v1/documents/batch_123456/status" \
  -H "X-API-Key: your_api_key"

# Knowledge base info
curl -X GET "https://api.raganything.com/v1/kb/default/info" \
  -H "X-API-Key: your_api_key"

# List documents
curl -X GET "https://api.raganything.com/v1/kb/default/documents?page=1&limit=10" \
  -H "X-API-Key: your_api_key"

# System health check (no auth required)
curl -X GET "https://api.raganything.com/v1/health"

# Detailed system status
curl -X GET "https://api.raganything.com/v1/status" \
  -H "X-API-Key: your_api_key"

# Streaming query with Server-Sent Events
curl -X GET "https://api.raganything.com/v1/query/text/stream?query=streaming%20example&mode=hybrid&api_key=your_api_key" \
  -H "Accept: text/event-stream" \
  -N

# Upload large file in chunks
curl -X POST "https://api.raganything.com/v1/files/upload/chunk" \
  -H "X-API-Key: your_api_key" \
  -F "upload_id=upload_123" \
  -F "chunk_index=0" \
  -F "total_chunks=5" \
  -F "chunk_data=@chunk_0.bin" \
  -F "filename=large_document.pdf"

# Generate API key (requires admin permissions)
curl -X POST "https://api.raganything.com/v1/auth/api-keys" \
  -H "Authorization: Bearer your_admin_jwt_token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Integration Key",
    "permissions": ["documents:read", "documents:write", "queries:execute"],
    "expires_in": 2592000
  }'

# Error handling example
curl -X POST "https://api.raganything.com/v1/query/text" \
  -H "X-API-Key: invalid_key" \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}' \
  -w "HTTP Status: %{http_code}\n"
```