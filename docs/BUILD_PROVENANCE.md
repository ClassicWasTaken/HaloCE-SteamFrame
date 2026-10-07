# Verify the installer and build inputs

The public Windows EXE is built by this repository's `.github/workflows/build.yml` after Windows/Linux tests, rootless-container checks and a complete native ARM64/OpenXR link. Release 1.4.2 adds GitHub's signed build-provenance attestation for that exact executable. It is separate from the downloadable asset and its checksum. Pull-request builds skip the attestation step; the verifier below requires the trusted main-branch source identity and does not accept a pull-request source ref.

Use a trusted installation of [GitHub CLI](https://cli.github.com/) to check the downloaded file:

```powershell
gh attestation verify Halo-Steam-Frame-Mod-Setup-1.4.2.exe --repo ClassicWasTaken/HaloSteamFrameMod --signer-workflow ClassicWasTaken/HaloSteamFrameMod/.github/workflows/build.yml --source-ref refs/heads/main --deny-self-hosted-runners
```

For a stricter check, add `--source-digest` followed by the release's installer commit. Read the command and repository identity from a trusted copy of this project or an independently saved reference. An attestation from a different project is not sufficient. [GitHub's verifier](https://cli.github.com/manual/gh_attestation_verify) checks the artifact digest and signed workflow/source identity; the [attestation documentation](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations) explains the trust model.

The release page also records SHA256 for accidental corruption and quick comparisons. A checksum fetched with the EXE alone does not independently authenticate a replacement of both. The EXE has no Windows Authenticode certificate; build provenance does not remove Windows' unsigned-application warning, establish the legal status of upstream sources, or prove that the software is free of vulnerabilities. It cannot protect against compromise of the authorized repository/workflow identity itself.

## Native build policy

The installer compiles the native program on the Frame using reviewed inputs:

- Engine: exact upstream commit `2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4` plus the shipped patch.
- Ubuntu 22.04 container: exact multi-architecture image digest, recorded in `BUILD_CONTAINER_IMAGE` in `resources/remote_install.py`.
- LLVM: major version 22, with the primary repository signing fingerprint `6084F3CF814B57C1CF12EFD515CF4D18AF4F7421` checked before the downloaded key is installed. The [LLVM repository](https://apt.llvm.org/) publishes that identity. The compiler must support the upstream `arm64_32` guest route.
- musl 1.2.5: repository-pinned archive SHA256 checked before extraction.
- SDL 3.4.16: exact Git commit, verified after checkout and before reuse.
- Bundled Paramiko source/license archive: repository-pinned URL and SHA256, independent of downloaded PyPI metadata. This archive is included for source/license compliance and is not installed or executed by the installer.

Ubuntu and LLVM's signed package updates remain enabled within those release/major-version channels. Installed package versions and the compiler version are recorded in the native build activity log. Maintainers review pin changes and run the full checks before each release. A rotated LLVM primary key, changed source archive or missing pinned revision stops the build until an updated installer is reviewed.

This policy favors maintained signed packages over a promise of byte-for-byte reproducible native builds. Apt package versions, dependency installation during the Windows build and operating-system libraries are not all frozen. Build attestations identify the released installer, while each Frame's native output hashes describe its own completed build; those hashes are not an independently established reproducible binary checksum. Downloaded OpenSSL/Tcl notices are bounded, non-executable licensing data with their resulting hashes recorded in the bundle manifest.

## USB and host trust

Automatic USB setup prefers the checksum-verified bundled ADB tools. An explicitly chosen ADB executable is the user's choice; SDK/PATH discovery is a fallback only when no bundle exists. A damaged bundle stops setup.

The installer requires a trusted Windows computer. A bundled client hash and a loopback-listener check do not authenticate an already-running ADB server against another process controlled by that same local user. Retained SSH host-key fingerprints are the Frame identity check for both USB and network connections. First use requires verifying the displayed fingerprint through a trusted Frame connection; do not accept an unexpected key or erase a saved fingerprint just to bypass a mismatch. The per-user `hosts.json` store is user-writable, so an attacker controlling that user account is outside this protection boundary. No blanket defense against a compromised local account is claimed.
