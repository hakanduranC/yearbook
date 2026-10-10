:8000 {
	encode zstd gzip
	handle /api/* {
		reverse_proxy api:8080 {
			flush_interval -1
		}
	}
	handle {
		reverse_proxy web:3000
	}
}
