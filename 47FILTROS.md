# Appendix C — Maintainability Screen Rules 

The rules comprising the maintainability screen were systematically derived through a strict dimensional exclusion process applied to the default rule sets of Hadolint and ShellCheck. To construct a clean metric that does not overlap with other quality dimensions, the selection followed four criteria. Baseline inclusion: all default-enabled rules related to code structure, notation, metadata, build logs, and shell correctness were initially considered. Performance exclusion: rules primarily targeting image-size optimization or layer-cache manipulation, such as cache cleanup, were deliberately removed, as their effect is already captured directly by ΔSize. Security exclusion: rules targeting security attack surfaces or privilege configurations were excluded to prevent duplication with ΔCVEs. Retained scope: the resulting 47 rules isolate structural correctness, clean notation, and maintainable authoring practices, acting as a proxy for the maintainability dimension alongside ΔInstr. 

The screen is applied to every extended-catalogue experiment. It is held as a single declarative rule list in the Data Extractor, so that it can be inspected and revised independently of the parsing logic. Rules that are disabled by default in Hadolint — notably the label-schema rules DL3049–DL3058 and the optional HEALTHCHECK rule DL3057 — are not part of the screen, since they do not fire unless explicitly configured. Table 7.1 lists the 47 rules, grouped by the sub-category that motivated their inclusion. 

|**Category**|**Rule ID**|**Source**|**Description / Objective**|
|---|---|---|---|
|**Reproducibility**|DL3005|Hadolint|Do not use apt-get dist-upgrade.|
||DL3006|Hadolint|Always tag the version of an image<br>explicitly.|
||DL3007|Hadolint|Using latest is prone to errors if<br>the image will ever update. Pin the<br>version explicitly to a release tag.|
||DL3008|Hadolint|Pin versions in apt-get install.|
||DL3013|Hadolint|Pin versions in pip.|
||DL3016|Hadolint|Pin versions in npm.|
||DL3017|Hadolint|Do not use apk upgrade.|
||DL3018|Hadolint|Pin versions in apk add.|
||DL3028|Hadolint|Pin versions in gem install.|
||DL3031|Hadolint|Do not use yum update.|
||DL3033|Hadolint|Specify version with yum install -y<br><package>-<version>.|
||DL3035|Hadolint|Do not use zypper update.|
||DL3037|Hadolint|Specify version with zypper install<br>-y <package>[=]<version>.|
||DL3039|Hadolint|Do not use dnf update.|
||DL3041|Hadolint|Specify version with dnf install -y<br><package>-<version>.|
||DL3062|Hadolint|Pin versions in go install.|



|**Category**|**Rule ID**|**Source**|**Description / Objective**|
|---|---|---|---|
|**Structural**<br>**correctness**|DL3000|Hadolint|Use absolute WORKDIR.|
||DL3003|Hadolint|Use absolute paths, or use<br>WORKDIR to switch to a directory.|
||DL3011|Hadolint|Valid UNIX ports range from 0 to<br>65535.|
||DL3012|Hadolint|Multiple HEALTHCHECK<br>instructions.|
||DL3021|Hadolint|COPY with more than 2 arguments<br>requires the last argument to end<br>with /.|
||DL3022|Hadolint|COPY --from should reference a<br>previously defned FROM alias.|
||DL3023|Hadolint|COPY --from cannot reference its<br>own FROM alias.|
||DL3024|Hadolint|FROM aliases (stage names) must<br>be unique.|
||DL3043|Hadolint|ONBUILD, FROM or MAINTAINER<br>triggered from within ONBUILD<br>instruction.|
||DL3044|Hadolint|Do not refer to an environment<br>variable within the same ENV<br>statement where it is defned.|
||DL3045|Hadolint|COPY to a relative destination<br>without WORKDIR set.|
||DL3061|Hadolint|Invalid instruction order.<br>Dockerfle must begin with FROM,<br>ARG or comment.|
||DL3063|Hadolint|Stage name should not be a|



|**Category**|**Rule ID**|**Source**|**Description / Objective**|
|---|---|---|---|
||||reserved word.|
||DL4003|Hadolint|Multiple CMD instructions found.<br>If you list more than one CMD then<br>only the last CMD will take efect.|
||DL4004|Hadolint|Multiple ENTRYPOINT instructions<br>found. If you list more than one<br>ENTRYPOINT then only the last<br>ENTRYPOINT will take efect.|
|**Usage and**<br>**notation**|DL3001|Hadolint|Command does not make sense<br>in a container.|
||DL3010|Hadolint|Use ADD for extracting archives<br>into an image.|
||DL3014|Hadolint|Use the -y switch.|
||DL3025|Hadolint|Use arguments JSON notation for<br>CMD and ENTRYPOINT<br>arguments.|
||DL3027|Hadolint|Do not use apt as it is meant to be<br>an end-user tool, use apt-get or<br>apt-cache instead.|
||DL3029|Hadolint|Do not use --platform= with<br>FROM.|
||DL3030|Hadolint|Use the -y switch to avoid manual<br>input yum install -y <package>.|
||DL3034|Hadolint|Non-interactive switch missing<br>from zypper command: zypper<br>install -y.|
||DL3038|Hadolint|Use the -y switch to avoid manual<br>input dnf install -y <package>.|
||DL4001|Hadolint|Either use Wget or Curl but not|



|**Category**|**Rule ID**|**Source**|**Description / Objective**|
|---|---|---|---|
||||both.|
||DL4005|Hadolint|Use SHELL to change the default<br>shell.|
||DL4006|Hadolint|Set the SHELL option -o pipefail<br>before RUN with a pipe in.|
|**Metadata**|DL4000|Hadolint|MAINTAINER is deprecated.|
|**Shell**<br>**correctness**<br>**(ShellCheck)**|SC2046|ShellCheck|Quote this to prevent word<br>splitting.|
||SC2086|ShellCheck|Double quote to prevent globbing<br>and word splitting.|
|**Build logs**|DL3047|Hadolint|Use wget --progress to avoid<br>excessively bloated build logs.|



Table Appendix C — Maintainability Screen Rules.1 - Complete list of the 47 rules comprising the maintainability screen, grouped by their respective sub-categories, including their identifier, source tool, and official description. 

