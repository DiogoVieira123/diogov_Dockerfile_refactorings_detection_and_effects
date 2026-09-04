# Test specification — commit pairs

Reference specification for the detection corpus. Each entry defines one pair of
commits over a single Dockerfile, the case type it exercises, and the rules that
must be reported on it.

Case types resolve to two expectations:

| Case type | Expectation | Purpose |
|---|---|---|
| Canonical | every listed rule must be reported | the refactoring in its textbook form |
| False-negative test | every listed rule must be reported | a syntactic variant that is easy to miss |
| Mixed | every listed rule must be reported | several refactorings performed in one commit |
| False-positive test | no listed rule may be reported | a change that resembles the rule without satisfying it |

---

## Index

| Pair | Artifact | Case type | Rules |
|---:|---|---|---|
| 0 | `services/api/Dockerfile` | Canonical | R02 |
| 1 | `services/api/Dockerfile` | Canonical | R01 |
| 2 | `services/worker/Dockerfile` | Canonical | R10 |
| 3 | `services/worker/Dockerfile` | Canonical | R12 |
| 4 | `services/auth/Dockerfile` | Mixed | R05, R14 |
| 5 | `services/auth/Dockerfile` | False-positive test | R05 |
| 6 | `services/api/Dockerfile` | Canonical | R08 |
| 7 | `services/api/Dockerfile` | Canonical | R13 |
| 8 | `services/worker/Dockerfile` | Canonical | R07 |
| 9 | `services/worker/Dockerfile` | False-positive test | R07 |
| 10 | `services/auth/Dockerfile` | False-negative test | R05 |
| 11 | `services/auth/Dockerfile` | Canonical | R14 |
| 12 | `services/api/Dockerfile` | False-positive test | R08 |
| 13 | `services/api/Dockerfile` | Canonical | R03 |
| 14 | `services/api/Dockerfile` | False-positive test | R03 |
| 15 | `services/worker/Dockerfile` | False-positive test | R09 |
| 16 | `services/worker/Dockerfile` | Canonical | R09 |
| 17 | `services/auth/Dockerfile` | False-negative test | R14 |
| 18 | `services/api/Dockerfile` | False-positive test | R13 |
| 19 | `services/api/Dockerfile` | False-positive test | R01 |
| 20 | `services/worker/Dockerfile` | False-negative test | R09 |
| 21 | `services/worker/Dockerfile` | False-negative test | R12 |
| 22 | `services/auth/Dockerfile` | False-positive test | R14 |
| 23 | `services/auth/Dockerfile` | False-positive test | R06 |
| 24 | `services/api/Dockerfile` | False-negative test | R01 |
| 25 | `services/api/Dockerfile` | False-positive test | R02 |
| 26 | `services/worker/Dockerfile` | False-positive test | R12 |
| 27 | `services/worker/Dockerfile` | Canonical | R04 |
| 28 | `services/auth/Dockerfile` | Canonical | R06 |
| 29 | `services/auth/Dockerfile` | False-negative test | R11 |
| 30 | `services/api/Dockerfile` | Canonical | R04 |
| 31 | `services/api/Dockerfile` | False-negative test | R02 |
| 32 | `services/api/Dockerfile` | False-negative test | R03 |
| 33 | `services/worker/Dockerfile` | False-positive test | R04 |
| 34 | `services/worker/Dockerfile` | False-negative test | R04 |
| 35 | `services/worker/Dockerfile` | False-positive test | R10 |
| 36 | `services/auth/Dockerfile` | False-negative test | R06 |
| 37 | `services/auth/Dockerfile` | Canonical | R11 |
| 38 | `services/api/Dockerfile` | False-negative test | R13 |
| 39 | `services/api/Dockerfile` | Mixed | R01, R08, R13 |
| 40 | `services/worker/Dockerfile` | False-negative test | R10 |
| 41 | `services/auth/Dockerfile` | False-positive test | R11 |
| 42 | `services/auth/Dockerfile` | Mixed | R02, R06, R14 |
| 43 | `services/api/Dockerfile` | False-negative test | R08 |
| 44 | `services/worker/Dockerfile` | False-negative test | R07 |
| 45 | `services/worker/Dockerfile` | Mixed | R07, R09, R12 |
| 46 | `services/auth/Dockerfile` | Mixed | R05, R10, R14 |
| 47 | `services/api/Dockerfile` | Mixed | R03, R04, R13 |
| 48 | `services/worker/Dockerfile` | Mixed | R01, R10, R13 |

---

## Pairs

### Pair 0

- **Artifact:** `services/api/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R02`
- **Expectation:** every listed rule must be reported
- **Commit before:** `7a3e568337f85fffd1e8787ca4a46f5333f39ea8`
- **Commit after:** `a68abe73781a0708b579197055a20e6b19a56c52`
- **Expected detection:** R02 reported once, the floating tag on the base image is replaced by an explicit released version

### Pair 1

- **Artifact:** `services/api/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R01`
- **Expectation:** every listed rule must be reported
- **Commit before:** `a68abe73781a0708b579197055a20e6b19a56c52`
- **Commit after:** `fced4529b845ca990ad54d8be6f0bbdc7d21f0f1`
- **Expected detection:** R01 reported once, three consecutive RUN instructions are aggregated into one

### Pair 2

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R10`
- **Expectation:** every listed rule must be reported
- **Commit before:** `17ca5eccf8b909a2043eb7095884a6304452ea0c`
- **Commit after:** `1204c8dd67b97f6a447b1b68e33e5e97a016e318`
- **Expected detection:** R10 reported once, a general purpose distribution base is replaced by the language image and the manual interpreter provisioning disappears with it

### Pair 3

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R12`
- **Expectation:** every listed rule must be reported
- **Commit before:** `1204c8dd67b97f6a447b1b68e33e5e97a016e318`
- **Commit after:** `3498fc6d8a93fa831f5af0210271f43b1882bc5c`
- **Expected detection:** R12 reported once, a redundant relocation of a copied file is removed and the copy writes to the final destination

### Pair 4

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** Mixed
- **Rules:** `R05`, `R14`
- **Expectation:** every listed rule must be reported
- **Commit before:** `25c70883c794f820807e9cdefae1267fc7684ffb`
- **Commit after:** `e6d35ca91c1d1ba00706a53a914e59fed8cc9f30`
- **Expected detection:** R05 and R14 reported, the build moves into its own stage with an alias and the runtime keeps only the produced binary

### Pair 5

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R05`
- **Expectation:** no listed rule may be reported
- **Commit before:** `e6d35ca91c1d1ba00706a53a914e59fed8cc9f30`
- **Commit after:** `f7f6107a59e89e193cda218e4b14a7869e85daad`

### Pair 6

- **Artifact:** `services/api/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R08`
- **Expectation:** every listed rule must be reported
- **Commit before:** `f7f6107a59e89e193cda218e4b14a7869e85daad`
- **Commit after:** `0ac6b7699ebbb79722ae6443abb8e7d4cea1d634`
- **Expected detection:** R08 reported for the three converted instructions

### Pair 7

- **Artifact:** `services/api/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R13`
- **Expectation:** every listed rule must be reported
- **Commit before:** `d80c1df1eadf255ca37960b81899e61c03442912`
- **Commit after:** `1d60d2b9cfe5ae6c4837706ada58f46eb3105d90`
- **Expected detection:** R13 reported once, the body of a RUN instruction is reformatted across continuation lines

### Pair 8

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R07`
- **Expectation:** every listed rule must be reported
- **Commit before:** `1d60d2b9cfe5ae6c4837706ada58f46eb3105d90`
- **Commit after:** `e90264c961f180ea7ad64bc7f173d6fee9c1f520`
- **Expected detection:** R07 reported once, the volatile source copy moves below the dependency installation with the instruction set unchanged

### Pair 9

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R07`
- **Expectation:** no listed rule may be reported
- **Commit before:** `e90264c961f180ea7ad64bc7f173d6fee9c1f520`
- **Commit after:** `724b8f0297f54da178306cd5072bec44b16a787f`

### Pair 10

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R05`
- **Expectation:** every listed rule must be reported
- **Commit before:** `966955cabb2bf618f82ed0ac5f7b22497eab4294`
- **Commit after:** `979dd14093158b244e8a4902bf15f6e9695a721a`
- **Expected detection:** R05 reported once, the extracted stage carries no alias, it is inserted above the existing stage and its output is pulled through a positional index

### Pair 11

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R14`
- **Expectation:** every listed rule must be reported
- **Commit before:** `979dd14093158b244e8a4902bf15f6e9695a721a`
- **Commit after:** `406e48e70c1abf44d7de7a02d22e7c29c8c16d47`
- **Expected detection:** R14 reported once, an alias is assigned to an unnamed stage and the positional reference is replaced by it

### Pair 12

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R08`
- **Expectation:** no listed rule may be reported
- **Commit before:** `406e48e70c1abf44d7de7a02d22e7c29c8c16d47`
- **Commit after:** `6f15b78eebbbdc990aeebeecf3f04d64a4b1c0d4`

### Pair 13

- **Artifact:** `services/api/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R03`
- **Expectation:** every listed rule must be reported
- **Commit before:** `6f15b78eebbbdc990aeebeecf3f04d64a4b1c0d4`
- **Commit after:** `cbb3bc265f316c07c3faf8cfd09a0ec4feac6f51`
- **Expected detection:** R03 reported for the three variables introduced and used further down the file

### Pair 14

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R03`
- **Expectation:** no listed rule may be reported
- **Commit before:** `cbb3bc265f316c07c3faf8cfd09a0ec4feac6f51`
- **Commit after:** `5b4d39b6422e92d20fd05ccace74e666bb0ec41e`

### Pair 15

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R09`
- **Expectation:** no listed rule may be reported
- **Commit before:** `5b4d39b6422e92d20fd05ccace74e666bb0ec41e`
- **Commit after:** `d6583f96565db2ffc16e63f5c19b52f138a5c14b`

### Pair 16

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R09`
- **Expectation:** every listed rule must be reported
- **Commit before:** `d6583f96565db2ffc16e63f5c19b52f138a5c14b`
- **Commit after:** `4acd35204b6066136a60b191820f05e80eed5c58`
- **Expected detection:** R09 reported once, a long chained RUN is extracted into an external script that the image copies in and executes

### Pair 17

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R14`
- **Expectation:** every listed rule must be reported
- **Commit before:** `c9c1a6282a6965c724e7eb16df66337f50825d6f`
- **Commit after:** `5cb6c318d53c4be63338f5d9be1289628a8b0c19`
- **Expected detection:** R14 reported once, an existing alias is replaced and one of its references lives in a FROM instruction where a later stage inherits from it

### Pair 18

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R13`
- **Expectation:** no listed rule may be reported
- **Commit before:** `05eecec711f035a067c6bc55d4071dc428478f6b`
- **Commit after:** `741f0eaa3d4112cf836a1d8c32b139863efb0f59`

### Pair 19

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R01`
- **Expectation:** no listed rule may be reported
- **Commit before:** `865169fd1542ec15a8271c7188102c6097e2fe2a`
- **Commit after:** `0e481a4ea4ddb784a15aedd0f392fb5c65c449c6`

### Pair 20

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R09`
- **Expectation:** every listed rule must be reported
- **Commit before:** `0e481a4ea4ddb784a15aedd0f392fb5c65c449c6`
- **Commit after:** `01ad7331b71d8b6386445470a6f1b21f648fa195`
- **Expected detection:** R09 reported once, the extraction adds no copy instruction because the script arrives inside the source tree copied above

### Pair 21

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R12`
- **Expectation:** every listed rule must be reported
- **Commit before:** `7e2b4a9c3bd5aa1361493e045928b667f370d4b2`
- **Commit after:** `2b3683b1ecfa18c6a62db2273e949abc316789b4`
- **Expected detection:** R12 reported once, the removed relocation sits in the middle of a chain of five commands behind a shell option line

### Pair 22

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R14`
- **Expectation:** no listed rule may be reported
- **Commit before:** `2b3683b1ecfa18c6a62db2273e949abc316789b4`
- **Commit after:** `e5c2ebc16e202f07edfe6eedac72bbfe7d0f27c5`

### Pair 23

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R06`
- **Expectation:** no listed rule may be reported
- **Commit before:** `e5c2ebc16e202f07edfe6eedac72bbfe7d0f27c5`
- **Commit after:** `5d9f652177c08a0d54ff5a2fcadf1237662efba5`

### Pair 24

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R01`
- **Expectation:** every listed rule must be reported
- **Commit before:** `4316c0896a7585c234f649a3de40288454e345d1`
- **Commit after:** `54b9d41288fbdf20395b6808a47c87731b7cb21c`
- **Expected detection:** R01 reported once, two RUN instructions in the JSON exec form separated by comments are aggregated into one

### Pair 25

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R02`
- **Expectation:** no listed rule may be reported
- **Commit before:** `54b9d41288fbdf20395b6808a47c87731b7cb21c`
- **Commit after:** `ff10bb7a8fc93785987d54d355a84034339b11c8`

### Pair 26

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R12`
- **Expectation:** no listed rule may be reported
- **Commit before:** `a519926e2a0ad4f45922d050ded83993f058ea51`
- **Commit after:** `249df77009b190a08a2022f78fffc6abd3c776a4`

### Pair 27

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R04`
- **Expectation:** every listed rule must be reported
- **Commit before:** `249df77009b190a08a2022f78fffc6abd3c776a4`
- **Commit after:** `eb74abfe6e8f0a6af895c9af27f761c4526a5711`
- **Expected detection:** R04 reported once for the build argument that now drives the base image reference

### Pair 28

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R06`
- **Expectation:** every listed rule must be reported
- **Commit before:** `eb74abfe6e8f0a6af895c9af27f761c4526a5711`
- **Commit after:** `5bc9178a87eb21c70ac5235b0024fefd4f3c5df5`
- **Expected detection:** R06 reported once, a stage sharing the runtime base image is collapsed into it and its stage reference disappears

### Pair 29

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R11`
- **Expectation:** every listed rule must be reported
- **Commit before:** `a360a9d89a7829461d042bc23cf1cb291221306f`
- **Commit after:** `cec0e2515e95fb666c4c427a30c49d3af8770d42`
- **Expected detection:** R11 reported once, the stage body migrates to an independent context while the stage header and its alias stay behind as a thin reference so the stage count and the consumer never change

### Pair 30

- **Artifact:** `services/api/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R04`
- **Expectation:** every listed rule must be reported
- **Commit before:** `cec0e2515e95fb666c4c427a30c49d3af8770d42`
- **Commit after:** `718ad826a1d501b76f48f6fd91c05e6b140ce78a`
- **Expected detection:** R04 reported once for the build argument that now drives the base image reference

### Pair 31

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R02`
- **Expectation:** every listed rule must be reported
- **Commit before:** `718ad826a1d501b76f48f6fd91c05e6b140ce78a`
- **Commit after:** `e29629c459ce8e8bc0e01a3f64b46d9c63b25a1a`
- **Expected detection:** R02 reported once, the effective base image tag changes through the default value of a build argument while the FROM line stays byte identical

### Pair 32

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R03`
- **Expectation:** every listed rule must be reported
- **Commit before:** `e29629c459ce8e8bc0e01a3f64b46d9c63b25a1a`
- **Commit after:** `9006fb00e4f495593370eb05ca474e7adda52fea`
- **Expected detection:** R03 reported for the three variables added through the legacy space separated form and a continuation block

### Pair 33

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R04`
- **Expectation:** no listed rule may be reported
- **Commit before:** `9006fb00e4f495593370eb05ca474e7adda52fea`
- **Commit after:** `834996307cccf63f69daad537bccacb827779471`

### Pair 34

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R04`
- **Expectation:** every listed rule must be reported
- **Commit before:** `834996307cccf63f69daad537bccacb827779471`
- **Commit after:** `ac259db3cad337c1c214e134b507ed20a2a0439b`
- **Expected detection:** R04 reported for BUILD_REVISION, declared without a default value in the global scope and repeated for stage scope

### Pair 35

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R10`
- **Expectation:** no listed rule may be reported
- **Commit before:** `ac259db3cad337c1c214e134b507ed20a2a0439b`
- **Commit after:** `8684e662b76e3b32884f591cb5645a3489664ca5`

### Pair 36

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R06`
- **Expectation:** every listed rule must be reported
- **Commit before:** `5156d4669ab234f5e0f36af6f9bb74e904c117fc`
- **Commit after:** `98fe3b065f4f1feb0966ab8b8e8cb05b92a7902d`
- **Expected detection:** R06 reported once, a stage is folded into another one while the file stays a multi stage build with stage references left

### Pair 37

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** Canonical
- **Rules:** `R11`
- **Expectation:** every listed rule must be reported
- **Commit before:** `98fe3b065f4f1feb0966ab8b8e8cb05b92a7902d`
- **Commit after:** `a1d8253b6d293cd775519787cf4339d164c17e3e`
- **Expected detection:** R11 reported once, a stage leaves the multi stage context and its artefacts arrive from the image published by that independent build

### Pair 38

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R13`
- **Expectation:** every listed rule must be reported
- **Commit before:** `a1d8253b6d293cd775519787cf4339d164c17e3e`
- **Commit after:** `46cdb7acd0c86b86ba446233bb8447ef92ed200a`
- **Expected detection:** R13 reported once, the RUN body is reformatted into a heredoc block that shell form parsers read as free text

### Pair 39

- **Artifact:** `services/api/Dockerfile`
- **Case type:** Mixed
- **Rules:** `R01`, `R08`, `R13`
- **Expectation:** every listed rule must be reported
- **Commit before:** `49bc58f0cf5a3646f04673708bf22ad6941619ce`
- **Commit after:** `da907131e0b8b527e23fad72751d99eb6dad5faa`
- **Expected detection:** R01, R08 and R13 reported on this revision of the api image

### Pair 40

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R10`
- **Expectation:** every listed rule must be reported
- **Commit before:** `f08c6f421051c3e077c7aca02f330da67d22a81a`
- **Commit after:** `69f7810ba3ed7cc66733fa86a015b2a9bb00ab10`
- **Expected detection:** R10 reported once, the base image of an intermediate stage is replaced while the first and the last FROM instructions of the file stay as they were

### Pair 41

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** False-positive test
- **Rules:** `R11`
- **Expectation:** no listed rule may be reported
- **Commit before:** `48023355a5d8fe8a072bf47f148eca88a56a31e7`
- **Commit after:** `4f533921ed1f37ece50a7c97808fe9513c6f27e4`

### Pair 42

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** Mixed
- **Rules:** `R02`, `R06`, `R14`
- **Expectation:** every listed rule must be reported
- **Commit before:** `fb49a31bf5d615b04f04034038b9a6e5b23bc8d1`
- **Commit after:** `3b2f51de1d3879f7e9bd23b9510183b6e8b2c49b`
- **Expected detection:** R02, R06 and R14 reported on this revision of the auth image

### Pair 43

- **Artifact:** `services/api/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R08`
- **Expectation:** every listed rule must be reported
- **Commit before:** `146247ded27227ef1fa773dd34ee61f0682a1991`
- **Commit after:** `694ff06297bafc48a48229605be203ab8223d10e`
- **Expected detection:** R08 reported for both instructions, converted while carrying an ownership flag and rewrapped across continuation lines

### Pair 44

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** False-negative test
- **Rules:** `R07`
- **Expectation:** every listed rule must be reported
- **Commit before:** `3ec74323f02273db1f4b2b4f78b84983d7e668e1`
- **Commit after:** `6781c2d64e11003116357f8721212506a6366e56`
- **Expected detection:** R07 reported once, the relocated instruction gains trailing separators in the same edit so the moved lines are not textually identical

### Pair 45

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** Mixed
- **Rules:** `R07`, `R09`, `R12`
- **Expectation:** every listed rule must be reported
- **Commit before:** `a1c9297351b0e12fbcf55fb63e41a19e1652a605`
- **Commit after:** `2bdfa49e9f2f8e994490475da69334469d2e5774`
- **Expected detection:** R07, R09 and R12 reported on this revision of the worker image

### Pair 46

- **Artifact:** `services/auth/Dockerfile`
- **Case type:** Mixed
- **Rules:** `R05`, `R10`, `R14`
- **Expectation:** every listed rule must be reported
- **Commit before:** `876aec710eb38d05f24458475513a52c7218c02a`
- **Commit after:** `3bd3cfdf51b7126d9757cb35217811403332764d`
- **Expected detection:** R05, R10 and R14 reported on this revision of the auth image

### Pair 47

- **Artifact:** `services/api/Dockerfile`
- **Case type:** Mixed
- **Rules:** `R03`, `R04`, `R13`
- **Expectation:** every listed rule must be reported
- **Commit before:** `3bd3cfdf51b7126d9757cb35217811403332764d`
- **Commit after:** `881cf9f92b8b0084348210e380e95780c11a80fe`
- **Expected detection:** R03, R04 and R13 reported on this revision of the api image

### Pair 48

- **Artifact:** `services/worker/Dockerfile`
- **Case type:** Mixed
- **Rules:** `R01`, `R10`, `R13`
- **Expectation:** every listed rule must be reported
- **Commit before:** `58d9f5c08257aba7d4edbf473fab1ec13a1d570d`
- **Commit after:** `98b472dcae70d251a5e6eabecf0383bb5f1b9fa4`
- **Expected detection:** R01, R10 and R13 reported on this revision of the worker image

