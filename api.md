# cloudrun.io API

endpoint: https://api.cloudrun.io/v1/

## POST /login

username=...&password=...

## GET /runner/

Returns runners list.

## GET /sizes

Returns available runner sizes.

## GET /runner/[name]/

Retrieves runner info (if POST, creates it if required).

```json
{
  "id": 122342,
  "name": "default",
  "timeout": 3600,
  "size": "medium",
  "region": "eu",
  "state": "running", // one of running/stopped/staritng
  "disk": 15, // disk usage in GB
  "projects": {
    "foo": {"image": "ubuntu-16.04", "ssh-host-key": "...", "ssh-authorized": ["..."], "external-ip": "...", "internal-ip": "..."},
    "bar": {"image": "ubuntu-16.04", "ssh-host-key": "...", "ssh-authorized": ["..."], "external-ip": "...", "internal-ip": "..."},
  },
}
```

## PUT /runner/[name]/

Changes settings. Allowed fields: type, timeout, state.

## DELETE /runner/[name]

Deletes an runner and its data.

## DELETE /runner/[name]/project/[name]

Delete project data.

## POST /runner/[name]/project/[name]

Create a new project. Args: "image".

## POST /runner/[name]/project/[name]/keys

Add a new authorized key. Args: "data".

## POST /runner/[name]/ping

Extends termination timeout.
