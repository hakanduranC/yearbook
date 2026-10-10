// Package storage wraps the S3 client for the private (originals) and public (variants) buckets.
// Everything is plain S3 so SeaweedFS in dev and R2 or Hetzner in prod differ only by config.
package storage

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"

	"yearbook/api/internal/config"
)

// Client talks to both buckets and knows how to build public URLs.
type Client struct {
	s3            *s3.Client
	presign       *s3.PresignClient
	Private       string
	Public        string
	publicBaseURL string
}

// New builds a Client from the environment configuration.
func New(ctx context.Context, cfg config.Config) (*Client, error) {
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(cfg.S3Region),
		awsconfig.WithCredentialsProvider(credentials.NewStaticCredentialsProvider(cfg.S3AccessKey, cfg.S3SecretKey, "")),
		// SeaweedFS and R2 reject the SDK's default CRC checksums; see docs/CONVENTIONS.md.
		awsconfig.WithRequestChecksumCalculation(aws.RequestChecksumCalculationWhenRequired),
		awsconfig.WithResponseChecksumValidation(aws.ResponseChecksumValidationWhenRequired),
	)
	if err != nil {
		return nil, fmt.Errorf("storage: %w", err)
	}
	client := s3.NewFromConfig(awsCfg, func(o *s3.Options) {
		o.BaseEndpoint = aws.String(cfg.S3Endpoint)
		o.UsePathStyle = cfg.S3ForcePathStyle
	})
	return &Client{
		s3:            client,
		presign:       s3.NewPresignClient(client),
		Private:       cfg.S3BucketPrivate,
		Public:        cfg.S3BucketPublic,
		publicBaseURL: strings.TrimRight(cfg.PublicBaseURL, "/"),
	}, nil
}

// PublicURL is PUBLIC_BASE_URL + "/" + key.
func (c *Client) PublicURL(key string) string {
	return c.publicBaseURL + "/" + key
}

// PresignedPut is a single presigned PUT; the client must send exactly these headers.
type PresignedPut struct {
	URL       string
	Headers   map[string]string
	ExpiresAt time.Time
}

// PresignPut signs a PUT of one object into the private bucket with the Content-Type bound.
func (c *Client) PresignPut(ctx context.Context, key, contentType string, ttl time.Duration) (PresignedPut, error) {
	req, err := c.presign.PresignPutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(c.Private),
		Key:         aws.String(key),
		ContentType: aws.String(contentType),
	}, s3.WithPresignExpires(ttl))
	if err != nil {
		return PresignedPut{}, fmt.Errorf("storage: presign put: %w", err)
	}
	headers := map[string]string{"Content-Type": contentType}
	for name, values := range req.SignedHeader {
		if strings.EqualFold(name, "host") || len(values) == 0 {
			continue
		}
		headers[name] = values[0]
	}
	return PresignedPut{URL: req.URL, Headers: headers, ExpiresAt: time.Now().UTC().Add(ttl)}, nil
}

// CreateMultipart starts a multipart upload and returns its id.
func (c *Client) CreateMultipart(ctx context.Context, key, contentType string) (string, error) {
	out, err := c.s3.CreateMultipartUpload(ctx, &s3.CreateMultipartUploadInput{
		Bucket:      aws.String(c.Private),
		Key:         aws.String(key),
		ContentType: aws.String(contentType),
	})
	if err != nil {
		return "", fmt.Errorf("storage: create multipart: %w", err)
	}
	return aws.ToString(out.UploadId), nil
}

// PresignPart signs the upload of one part.
func (c *Client) PresignPart(ctx context.Context, key, uploadID string, partNumber int32, ttl time.Duration) (string, error) {
	req, err := c.presign.PresignUploadPart(ctx, &s3.UploadPartInput{
		Bucket:     aws.String(c.Private),
		Key:        aws.String(key),
		UploadId:   aws.String(uploadID),
		PartNumber: aws.Int32(partNumber),
	}, s3.WithPresignExpires(ttl))
	if err != nil {
		return "", fmt.Errorf("storage: presign part: %w", err)
	}
	return req.URL, nil
}

// Part is one received part of a multipart upload.
type Part struct {
	Number int32
	ETag   string
}

// ListParts returns the parts storage has already received.
func (c *Client) ListParts(ctx context.Context, key, uploadID string) ([]Part, error) {
	var parts []Part
	var marker *int32
	for {
		out, err := c.s3.ListParts(ctx, &s3.ListPartsInput{
			Bucket:           aws.String(c.Private),
			Key:              aws.String(key),
			UploadId:         aws.String(uploadID),
			PartNumberMarker: markerString(marker),
		})
		if err != nil {
			return nil, fmt.Errorf("storage: list parts: %w", err)
		}
		for _, p := range out.Parts {
			parts = append(parts, Part{Number: aws.ToInt32(p.PartNumber), ETag: aws.ToString(p.ETag)})
		}
		if !aws.ToBool(out.IsTruncated) || out.NextPartNumberMarker == nil {
			return parts, nil
		}
		next, err := parsePartMarker(aws.ToString(out.NextPartNumberMarker))
		if err != nil {
			return parts, nil
		}
		marker = &next
	}
}

// CompleteMultipart assembles the parts into the final object.
func (c *Client) CompleteMultipart(ctx context.Context, key, uploadID string, parts []Part) error {
	completed := make([]types.CompletedPart, 0, len(parts))
	for _, p := range parts {
		completed = append(completed, types.CompletedPart{PartNumber: aws.Int32(p.Number), ETag: aws.String(p.ETag)})
	}
	_, err := c.s3.CompleteMultipartUpload(ctx, &s3.CompleteMultipartUploadInput{
		Bucket:          aws.String(c.Private),
		Key:             aws.String(key),
		UploadId:        aws.String(uploadID),
		MultipartUpload: &types.CompletedMultipartUpload{Parts: completed},
	})
	if err != nil {
		return fmt.Errorf("storage: complete multipart: %w", err)
	}
	return nil
}

// AbortMultipart discards an unfinished multipart upload. Unknown uploads are not an error.
func (c *Client) AbortMultipart(ctx context.Context, key, uploadID string) error {
	_, err := c.s3.AbortMultipartUpload(ctx, &s3.AbortMultipartUploadInput{
		Bucket:   aws.String(c.Private),
		Key:      aws.String(key),
		UploadId: aws.String(uploadID),
	})
	var nf *types.NoSuchUpload
	if errors.As(err, &nf) {
		return nil
	}
	return err
}

// Head returns the size of a private object, or ok=false when it does not exist.
func (c *Client) Head(ctx context.Context, bucket, key string) (size int64, ok bool, err error) {
	out, err := c.s3.HeadObject(ctx, &s3.HeadObjectInput{Bucket: aws.String(bucket), Key: aws.String(key)})
	if err != nil {
		var nf *types.NotFound
		if errors.As(err, &nf) || strings.Contains(err.Error(), "404") {
			return 0, false, nil
		}
		return 0, false, fmt.Errorf("storage: head: %w", err)
	}
	return aws.ToInt64(out.ContentLength), true, nil
}

// Get opens an object for streaming; the caller closes the body.
func (c *Client) Get(ctx context.Context, bucket, key string) (io.ReadCloser, int64, error) {
	out, err := c.s3.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(bucket), Key: aws.String(key)})
	if err != nil {
		return nil, 0, fmt.Errorf("storage: get %s: %w", key, err)
	}
	return out.Body, aws.ToInt64(out.ContentLength), nil
}

// Put uploads a whole object (used by ybctl seed, not by the request path).
func (c *Client) Put(ctx context.Context, bucket, key, contentType string, body io.Reader, size int64) error {
	_, err := c.s3.PutObject(ctx, &s3.PutObjectInput{
		Bucket:        aws.String(bucket),
		Key:           aws.String(key),
		ContentType:   aws.String(contentType),
		Body:          body,
		ContentLength: aws.Int64(size),
	})
	if err != nil {
		return fmt.Errorf("storage: put %s: %w", key, err)
	}
	return nil
}

// Delete removes one object; missing objects are not an error.
func (c *Client) Delete(ctx context.Context, bucket, key string) error {
	_, err := c.s3.DeleteObject(ctx, &s3.DeleteObjectInput{Bucket: aws.String(bucket), Key: aws.String(key)})
	return err
}

// PresignGet signs a download of a private object, served as an attachment with filename.
func (c *Client) PresignGet(ctx context.Context, key, filename string, ttl time.Duration) (string, error) {
	req, err := c.presign.PresignGetObject(ctx, &s3.GetObjectInput{
		Bucket:                     aws.String(c.Private),
		Key:                        aws.String(key),
		ResponseContentDisposition: aws.String(fmt.Sprintf("attachment; filename=%q", filename)),
	}, s3.WithPresignExpires(ttl))
	if err != nil {
		return "", fmt.Errorf("storage: presign get: %w", err)
	}
	return req.URL, nil
}

func markerString(m *int32) *string {
	if m == nil {
		return nil
	}
	return aws.String(fmt.Sprint(*m))
}

func parsePartMarker(s string) (int32, error) {
	var n int32
	_, err := fmt.Sscanf(s, "%d", &n)
	return n, err
}
