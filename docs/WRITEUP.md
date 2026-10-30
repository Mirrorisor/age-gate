# I built a website that checks your age without seeing your ID

I'm a complete beginner at coding, writing this from Perth. I started by asking what technology I could build for Zcash, and I ended up somewhere I didn't expect: proving your age without handing over your identity.

Here's the short version of what I did: I built a small website where a page only opens after your phone proves you're over 18. The proof is a zero-knowledge proof, which means my site learns one thing, "yes", and never sees a birthdate, a name or an ID. Then I added a second gate: a tiny shielded Zcash payment. All of it runs on test certificates and test coins. It is a learning project, not something to protect real people.

I built this with an AI assistant (Claude) doing a lot of the coding and explaining, while I ran every command, tested it on my own laptop and phone, and made the decisions. This is also how the project I used for payments, ZecCheckout, describes its own development.

## What actually happened

**The age check worked, with two different wallets.** I tried the Multipaz test app and the EU's age verification app on my Android phone, each with a different test issuer. The same open-source verifier accepted both, once I told it which test root certificates to trust. Seeing "Members area: you passed the age check" appear after a proof from my own phone was the moment it stopped feeling theoretical.

**Then the payment step.** After the age check, the site asks for 0.001 test ZEC. I ran ZecCheckout, a self-hosted checkout that holds only a viewing key (it can see a payment arrive but can never spend). I paid from a Zingo desktop wallet on testnet, and a few minutes later, after three confirmations, the members page opened by itself. The shop learned that an invoice was paid, not who paid it.

## What tripped me up

I'm putting these here because they cost me hours and might save you some:

1. **"Untrusted issuer" says nothing else.** When the verifier rejected a credential, it didn't say whose certificate it had seen. I ended up patching the verifier on my machine just to print the issuer name. I wrote a small tool that lists every certificate you currently trust, and I reported the missing detail to the maintainers: https://github.com/pipe23-org/zk-age-verifier/issues/76
2. **Trust lists can contain more than they look like.** The verifier can load an ETSI trust list, but it adds every certificate in the file as trusted. The EU example list I downloaded held only signing certificates, so loading it would have trusted the wrong things. I checked before using it and threw it away. I checked the latest code later and it still behaves that way. That's in the same issue.
3. **Size limits and one document type.** The proof circuit only accepts documents up to a certain size, and the verifier only accepts the EU age verification document type. A normal driving licence won't work yet.
4. **Windows.** The verifier's compiled library has no Windows build, so everything runs in Docker.
5. **Getting test coins took longest of all.** I needed a wallet that supports testnet (Zingo lets you pick the network when you create the wallet, and you can't change it afterwards) and some coins. One faucet looked funded but showed zero payouts in 24 hours and refused my addresses, so I asked people instead, and someone on the Zcash Foundation team kindly sent me 2 test ZEC.
6. **Small traps:** a viewing key got damaged when I copied it, and an old paid invoice in my browser made the payment page skip itself.

## Update: I sent a fix

After posting the issue I wrote the missing log line myself and offered it to the maintainers as a pull request. It logs which certificate was refused, so an operator can see why; the person presenting the credential still only sees "untrusted issuer". A first-time contributor's automated checks wait for a maintainer to approve them, so while I wait I run my own copy of the verifier (a fork) in my age gate: https://github.com/Mirrorisor/zk-age-verifier

Setting that up taught me two more things. A real test certificate in the verifier's test suite expired on 24 September 2026, which made one of its tests fail for everyone, so in my fork I pinned the clock in that test. And a fork has a cost: security fixes from the original project don't arrive by themselves, I have to bring them over by hand. I looked at writing my own verifier instead and decided against it: the hard part is the cryptography, and a mistake there would silently let the wrong people in or keep the right ones out.

The second half of the issue, the trust-list loader, I fixed in the fork only, because it changes behaviour and the maintainers haven't been asked yet. A trust list now only trusts the certificates listed under a service, not the list's own signer or its old service versions. It still doesn't check the list's signature, and the docs now say so plainly.

Then I went back over my own site. The biggest hole was dull: with no secret key set, the site used a fixed default, and anyone who knows the default can forge a "passed the age check" cookie. It now makes a random key instead. I also added rate limits, browser security headers, and a proper web server. I got one thing wrong along the way: I capped request sizes at 64 KB, and the wallet's proof is much bigger, so the age check broke on my own phone until I raised the limit for that one route. A real device found in a minute what my tests had missed.
Since then I've kept improving my fork, and sent the trust-list change upstream as its own pull request (the log line is #77, the trust list is #78). Two additions came out of debugging my own setup. The log line now also records the whole refused certificate, and the fork has a way to ask a certificate why it is not trusted: you give it a certificate and it prints each check (is it in date, does it allow signatures, is the key the right type, which of your trusted roots signed it) and ends with TRUSTED or NOT TRUSTED, without starting the service. I ran it on my four trusted roots and all four said NOT TRUSTED, which is correct: they are certificate authorities, not the document signers a phone presents. A trust list can also now be pinned to a hash, so a changed file is refused. And it found something I would have missed: one of the test roots I trust has a serial number of zero, which a library the verifier uses will refuse in a future release. I added a test that fails the day that happens, so I find out in a build and not on a user's phone. There is a troubleshooting page in the fork now too.

On my own site I wrote a test that checks the privacy page tells the truth: it runs a whole age check and payment and fails if the session cookie ever holds anything beyond a session id, a yes flag and an invoice number, if the wallet's proof is echoed back, if a page loads anything from another site, or if the site sets a cookie just for visiting. I also pulled the age check out into a small reusable piece for Flask sites, with its own page of instructions, so you can add it to a site in a few lines.
My pull request and the issue: https://github.com/pipe23-org/zk-age-verifier/pulls?q=author%3AMirrorisor
## Update: passports too

I added a second way in: proving you are 18 or over with a passport, through the ZKPassport app. The site shows a QR code (a link on a phone), the app reads the passport chip and makes the proof, and a small service on my side checks it. It never goes to ZKPassport's own verifier, the site rebuilds the question itself (so a visitor can't swap it for an easier one), and it throws away the per-site identifier the proof carries, so visits can't be linked. The site learns one thing: this person is 18 or over.

I tested it end to end without a real passport, using a stand-in for the app that proves from a mock passport of a made-up country. A mock adult got through the age check, paid a shielded testnet payment and reached the members page. A mock child couldn't even make the proof.

Reviewing my own code, I found a hole: nothing tied a proof to the visit that asked for it. Anyone who got hold of a valid "over 18" proof could have handed it to the site again from another browser. The fix is small. Every visit to the passport page now gets its own random scope, the proof is made for that scope, and the site accepts it once. I tested it by capturing a real proof and sending it back: in the same visit it was refused because the scope was used up, and in a new visit the checker said the proof used a different scope than the one expected.

Two honest limits. This is still mock passports only, and I left it that way on purpose: ZKPassport says it has not had an external audit, and neither has my side. And while writing the tests I found one of mine that only passed when the verifier was switched off, because a running verifier finished the first upload and cleared the session before the second one was checked. It was a bad test, not a bad site, but I would not have found it without running everything on my own machine.

## What this is not

It isn't secure enough for real users or real money. The verifier calls itself pre-alpha. ZecCheckout is a prototype that uses a public server and doesn't verify proof-of-work, so a hostile server could make an unpaid invoice look paid. For anything real you'd want your own node, real issuers, a proper database, and a review by someone who does this for a living. I also haven't tested any real government-issued credential, so I can't say yet which wallets and issuers will exist for Australians.

## Why I think it's worth watching

A website can enforce an age rule and take a payment while collecting nothing it could leak. The parts are open source, and a beginner with patience could get them running in a weekend. The rough edges (error messages, trust lists, documentation) are exactly where small contributions help. If you try it, or you spot something I've got wrong, I'd like to hear about it.

Code: https://github.com/Mirrorisor/age-gate

Thanks to: Google's Longfellow ZK, pipe23-org (the verifier), the OpenWallet Foundation (Multipaz), the EU age verification project, Zingo Labs (Zingo wallet), the Zcash Foundation (Zebra, and for the test coins), and Samizdat Project (ZecCheckout).
