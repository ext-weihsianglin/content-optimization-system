

**Welcome to Profound\!**

We are so excited to have the opportunity to work with you.

In this work trial, we’ll provide you will work on a project that is directly related to our business.

A few points to keep in mind:

* Feel free to use your own laptop and any coding tools needed. We can give you access to OpenAI API (feel free to email us).  
* We don’t expect you to fully solve a complex problem during your time. However, we do expect you to deliver some complete, actionable work and outline what next steps you would take if you were working at Profound full time.  
* At the end of your trial, you’ll present your work to the team.  
* Feel free to reach out to Ali, Sid, Brandon or Dimas or anyone else at the company. We don't want you to be blocked at any point.  
* Please also share feedback if anything is unclear. While we’ve tried our best to design this project around real business priorities, there may be details we’ve overlooked. Call them out, propose reasonable assumptions or adjustments, and keep moving forward. We highly value speed of execution.

**Content Generation based on AEO signals**

**Context**

When generating content for our clients, it’s not enough to know what reads well \- we also need to understand what performs well in answer engines. Certain on-page elements and semantic patterns cause some pages to be cited or referenced far more often than others.

Your task is to identify which HTML and content-level factors make a page more likely to be cited for a particular target user query and then build a lightweight content generation tool that applies these learnings \- a system capable of producing or refining page content that aligns with the features most associated with high citation likelihood.

In other words: first, discover what good content looks like to answer engines \- then generate it.

**Task Overview**

You’ll be analyzing and generating content to understand **what makes certain pages more likely to be cited by LLMs** when responding to user queries.

**Inputs**

You’ll be provided with:

- **A dataset of top and bottom performing pages** for a given hostname.  
  - For example, if the hostname is `ramp.com`, perhaps `ramp.com/blog/xxx` is frequently cited by LLMs, but `ramp.com/careers/yyy` is cited far less often  
  - **Remember the** top bottom denotes the citation standard for a *given* **hostname,** not overall

The data has the following schema:

Example:

| prompt | citation\_category | href | hostname | html\_content |
| :---- | :---- | :---- | :---- | :---- |
|   running shoes | top | https\://www\.runnersworld.com/gear/a19663621/best-running-shoes/ | runnersworld.com | \<html\> …  |
| Best running shoes | bottom | https\://www\.nike.com/men | nike.com | \<html\> .. |
| … | … | … | … | … |

The dataset can be found here (split across multiple parquet files):

[**Citations Dataset**](https://drive.google.com/drive/folders/1bnc2ioGP-KV8quOdvB7_cwFgSUedMKg8?usp=sharing)

- **Prompt associations** for each page  
  - The specific user query that led to it being cited. You may assume that the page was optimized for that user query  
    - Both top- and bottom-cited pages will have associated prompts since they were all surfaced by answer engines to some degree  
- **Scraped content** for each page, including:  
  - The **raw HTML**  
  - The **cleaned markdown** representation of the main body text  
- For each hostname, there are at most 5 top and 5 bottom citations

Once you’ve identified the key factors or signals that appear to drive higher citation rates, your second task is to **generate new content optimized for a given query** using those insights.

For example, for a query like :

*“What are the best running shoes”*

you should be able to generate a **draft webpage or markdown section** that reflects the on-page and structural patterns you discovered